"""
clima.py
--------
Combinador de fuentes climáticas. Arma una única serie diaria de precipitación
y ETo tomando cada día de la mejor fuente disponible, y deja registrado de
dónde salió cada dato.

Orden por defecto (configurable en config.yaml → clima.fuentes):

    1. siga        pluviómetro del INTA, el dato medido más cercano al lote
    2. openmeteo   grilla de ~9 km, llega hasta ayer, además da pronóstico
    3. agera5      reanálisis de Copernicus, homogéneo pero con ~10 días de atraso

La prioridad se aplica por día y por variable: si la estación tiene lluvia pero
le falta un día de ETo, ese día la ETo sale de Open-Meteo y la lluvia sigue
siendo la medida. Las columnas `fuente_pp` y `fuente_eto` guardan el origen de
cada valor, de modo que una serie mezclada siempre pueda auditarse.

Advertencia que conviene no perder de vista: las fuentes no son equivalentes.
Medido sobre el lote de Manfredi en septiembre de 2026, Open-Meteo entregó un
22 % más de lluvia que el pluviómetro en 30 días, y AgERA5 un 29 % menos en 21
días. Mezclar fuentes a mitad de campaña introduce un escalón en la serie; el
registro de origen por día permite al menos verlo.
"""
from __future__ import annotations

import logging
from typing import Callable, Iterable

import pandas as pd

logger = logging.getLogger(__name__)

VARIABLES = ("precipitacion_mm", "eto_mm")


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Deja el DataFrame con fecha normalizada y solo las columnas de interés."""
    d = df.copy()
    d["fecha"] = pd.to_datetime(d["fecha"]).dt.normalize()
    for v in VARIABLES:
        if v not in d.columns:
            d[v] = pd.NA
    d = d[["fecha", *VARIABLES]]
    return d.sort_values("fecha").drop_duplicates("fecha")


def combinar(
    fuentes: Iterable[tuple[str, Callable[[], pd.DataFrame]]],
    fecha_inicio: str,
    fecha_fin: str,
) -> tuple[pd.DataFrame, dict]:
    """Combina fuentes por prioridad.

    `fuentes` es una secuencia de (nombre, función) en orden de preferencia. La
    función se llama solo si todavía quedan días por cubrir, y si falla se
    registra el motivo y se sigue con la siguiente: una fuente caída nunca debe
    tumbar la corrida.
    """
    calendario = pd.date_range(fecha_inicio, fecha_fin, freq="D")
    salida = pd.DataFrame({"fecha": calendario})
    for v in VARIABLES:
        salida[v] = pd.NA
        salida[f"fuente_{'pp' if v == 'precipitacion_mm' else 'eto'}"] = pd.NA

    detalle: dict = {"usadas": {}, "fallidas": {}, "estacion": None}

    for nombre, obtener in fuentes:
        pendientes = {
            v: salida[v].isna().sum() for v in VARIABLES
        }
        if not any(pendientes.values()):
            break

        try:
            df = obtener()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fuente '%s' no disponible: %s", nombre, exc)
            detalle["fallidas"][nombre] = str(exc)
            continue

        if df is None or df.empty:
            detalle["fallidas"][nombre] = "sin datos en el rango"
            continue

        df = _normalizar(df)
        salida = salida.merge(df, on="fecha", how="left", suffixes=("", "_nueva"))

        for v in VARIABLES:
            col_origen = f"fuente_{'pp' if v == 'precipitacion_mm' else 'eto'}"
            nueva = salida[f"{v}_nueva"]
            hueco = salida[v].isna() & nueva.notna()
            salida.loc[hueco, v] = nueva[hueco]
            salida.loc[hueco, col_origen] = nombre
            detalle["usadas"].setdefault(nombre, {})[v] = int(hueco.sum())
            salida = salida.drop(columns=[f"{v}_nueva"])

    faltantes = {v: int(salida[v].isna().sum()) for v in VARIABLES}
    if any(faltantes.values()):
        logger.warning(
            "Quedaron días sin dato climático: %s. Esos días se procesan con 0.",
            faltantes,
        )
    detalle["faltantes"] = faltantes

    for nombre, vs in detalle["usadas"].items():
        logger.info(
            "Clima · %s aportó %d días de lluvia y %d de ETo.",
            nombre, vs.get("precipitacion_mm", 0), vs.get("eto_mm", 0),
        )

    return salida, detalle


def armar_fuentes(cfg: dict, bbox, fecha_inicio: str, fecha_fin: str) -> list:
    """Construye la lista de (nombre, función) según config.yaml.

    Los imports van adentro para que, por ejemplo, no haga falta tener cdsapi
    instalado si AgERA5 no está en la lista.
    """
    cfg_clima = cfg.get("clima", {})
    orden = cfg_clima.get("fuentes") or [cfg_clima.get("fuente", "openmeteo")]
    tz = cfg_clima.get("zona_horaria", "America/Argentina/Cordoba")
    estacion_elegida: dict = {}

    def _siga():
        from .clima_siga import descargar_siga
        cfg_siga = cfg_clima.get("siga", {})
        df, est = descargar_siga(
            fecha_inicio, fecha_fin, bbox,
            estacion_id=cfg_siga.get("estacion_id"),
            max_km=float(cfg_siga.get("max_km", 50)),
            krs=float(cfg_siga.get("krs", 0.16)),
        )
        estacion_elegida.update(est)
        return df

    def _openmeteo():
        from .clima_openmeteo import descargar_openmeteo
        df = descargar_openmeteo(
            fecha_inicio, fecha_fin, bbox,
            modelo_archivo=cfg_clima.get("modelo_archivo"),
            zona_horaria=tz,
        )
        return df.drop(columns=["fuente"], errors="ignore")

    def _agera5():
        from .clima_agera5 import descargar_agera5
        return descargar_agera5(
            fecha_inicio, fecha_fin, bbox,
            request_template=cfg["cds"]["request_template"],
        )

    disponibles = {"siga": _siga, "openmeteo": _openmeteo, "agera5": _agera5}
    fuentes = []
    for nombre in orden:
        clave = str(nombre).strip().lower()
        if clave not in disponibles:
            logger.warning("Fuente de clima desconocida en config: '%s'.", nombre)
            continue
        fuentes.append((clave, disponibles[clave]))

    if not fuentes:
        raise ValueError(
            "config.yaml: clima.fuentes no tiene ninguna fuente válida "
            "(siga, openmeteo, agera5)."
        )
    return fuentes, estacion_elegida


def resumen_origen(df: pd.DataFrame) -> str:
    """Una línea con el origen de los datos, para el log y la documentación."""
    partes = []
    for col, etiqueta in (("fuente_pp", "lluvia"), ("fuente_eto", "ETo")):
        if col in df.columns:
            conteo = df[col].value_counts().to_dict()
            partes.append(
                f"{etiqueta}: " + ", ".join(f"{k} {v}d" for k, v in conteo.items())
            )
    return " | ".join(partes) if partes else "sin datos"
