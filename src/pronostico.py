"""
pronostico.py
-------------
Proyecta el balance hídrico hacia adelante con el pronóstico de Open-Meteo,
para avisar que el lote va a cruzar el umbral de riego antes de que ocurra.

Es una simulación: NO toca el estado persistente ni el CSV histórico. Parte
del estado real del último día calculado y corre los días pronosticados sobre
una copia, de modo que la próxima corrida real arranca igual que si esto no
existiera.

El NDVI no se pronostica. Se sostiene el último valor observado, que para unos
pocos días es razonable en un cultivo instalado y es la misma suposición que ya
hace el balance cuando las nubes tapan una pasada. En un cultivo que está
secándose o en plena expansión foliar, esa suposición subestima o sobreestima
el consumo: por eso el horizonte conviene corto.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

import pandas as pd

from .balance import EstadoBalance, precipitacion_efectiva, procesar_dias_nuevos

logger = logging.getLogger(__name__)


def proyectar(
    estado: EstadoBalance,
    df_pronostico: pd.DataFrame,
    df_suelo: pd.DataFrame,
    ndvi_actual: Optional[float],
    umbral_riego_pct: float,
    **kwargs_balance,
) -> pd.DataFrame:
    """Corre el balance sobre los días pronosticados, sin alterar el estado.

    `kwargs_balance` son los mismos parámetros que recibe el balance real
    (kc_a, kc_b, recarga_por_capa, tabla_prof_raiz, fecha_siembra, etc.), para
    que la proyección use exactamente la misma física que la corrida diaria.
    """
    if df_pronostico.empty:
        return pd.DataFrame()

    ndvi = ndvi_actual if ndvi_actual is not None else estado.ultimo_ndvi_valido
    datos = pd.DataFrame(
        {
            "fecha": df_pronostico["fecha"],
            "precipitacion_mm": df_pronostico["precipitacion_mm"],
            "eto_mm": df_pronostico["eto_mm"],
            "ndvi": ndvi,
            "riego_mm": 0.0,
        }
    )

    # Copia del estado: la proyección no debe dejar rastro
    estado_sim = replace(estado)
    df, _ = procesar_dias_nuevos(
        datos, estado_sim, df_suelo, umbral_riego_pct=umbral_riego_pct,
        **kwargs_balance
    )
    return df


def primer_cruce(df_proyeccion: pd.DataFrame, umbral_pct: float) -> Optional[dict]:
    """Primer día proyectado en que el agua útil cae por debajo del umbral."""
    if df_proyeccion.empty:
        return None
    bajo = df_proyeccion[df_proyeccion["pct_au"] < umbral_pct]
    if bajo.empty:
        return None
    fila = bajo.iloc[0]
    hoy = pd.Timestamp.today().normalize()
    return {
        "fecha": pd.to_datetime(fila["fecha"]),
        "dias": int((pd.to_datetime(fila["fecha"]) - hoy).days),
        "pct_au": float(fila["pct_au"]),
        "au_real_mm": float(fila["au_real_mm"]),
    }


def lamina_ajustada(
    lamina_neta_mm: float,
    df_pronostico: Optional[pd.DataFrame],
    eficiencia_aplicacion: float = 0.85,
    dias_descuento: int = 3,
    umbral_lluvia_efectiva_mm: float = 15.0,
) -> Optional[dict]:
    """Lámina de riego descontando la lluvia pronosticada a corto plazo.

    La lámina sugerida clásica responde "cuánto falta HOY para llegar a
    capacidad de campo". Esta responde "cuánto conviene aplicar HOY si en los
    próximos días va a llover lo que dice el pronóstico". Son dos números
    distintos y los dos sirven: el primero es la necesidad del cultivo, el
    segundo es la decisión de manejo.

    Decisiones de cálculo, explícitas porque cambian el resultado:

      * Se descuenta lluvia EFECTIVA, no lluvia caída, con la misma fórmula
        que usa el balance (USDA-SCS por encima del umbral). Descontar los
        milímetros brutos sobreestimaría el aporte: de un evento de 40 mm no
        entran 40 al perfil.
      * La ventana es corta a propósito (3 días por defecto). Más allá de eso
        el pronóstico de lluvia convectiva en la región no sostiene una
        decisión de riego, y descontar una lluvia que no llega deja al
        cultivo en estrés.
      * El descuento se topea en la lámina neta: si llueve más que el
        déficit, la lámina ajustada es cero, no negativa. El excedente
        percola, no se guarda.

    Devuelve None si no hay pronóstico para descontar.
    """
    if df_pronostico is None or df_pronostico.empty:
        return None

    dias = max(1, int(dias_descuento))
    ventana = df_pronostico.sort_values("fecha").head(dias)
    if ventana.empty:
        return None

    efectiva = float(
        sum(
            precipitacion_efectiva(float(pp), umbral_lluvia_efectiva_mm)
            for pp in ventana["precipitacion_mm"]
        )
    )
    descuento = min(efectiva, float(lamina_neta_mm))
    neta = max(0.0, float(lamina_neta_mm) - descuento)
    bruta = neta / eficiencia_aplicacion if eficiencia_aplicacion > 0 else 0.0

    return {
        "lamina_neta_mm": round(neta, 1),
        "lamina_bruta_mm": round(bruta, 1),
        "descuento_mm": round(descuento, 1),
        "lluvia_pronosticada_mm": round(float(ventana["precipitacion_mm"].sum()), 1),
        "lluvia_efectiva_mm": round(efectiva, 1),
        "ventana_dias": int(len(ventana)),
        "hasta": str(pd.to_datetime(ventana["fecha"].max()).date()),
    }


def resumir(
    df_proyeccion: pd.DataFrame,
    umbral_pct: float,
    ya_en_deficit: bool,
) -> Optional[str]:
    """Línea para el mensaje de Telegram, o None si no hay nada que decir.

    No se emite aviso anticipado cuando el lote ya está por debajo del umbral:
    en ese caso el mensaje principal ya dice que hay que regar y agregar una
    proyección solo agrega ruido.
    """
    if df_proyeccion.empty:
        return None

    lluvia = float(df_proyeccion["precipitacion_mm"].sum())
    dias = len(df_proyeccion)
    hasta = pd.to_datetime(df_proyeccion["fecha"].max()).strftime("%d/%m")

    if ya_en_deficit:
        if lluvia >= 1:
            return (f"Pronóstico: {lluvia:.0f} mm de lluvia en los próximos "
                    f"{dias} días (hasta el {hasta}).")
        return (f"Pronóstico: sin lluvias significativas en los próximos "
                f"{dias} días.")

    cruce = primer_cruce(df_proyeccion, umbral_pct)
    if cruce is None:
        final = df_proyeccion.iloc[-1]
        return (f"Proyección a {dias} días: no cruza el umbral; quedaría en "
                f"{final['pct_au']:.0f} % el {hasta}. "
                f"Lluvia esperada: {lluvia:.0f} mm.")

    cuando = cruce["fecha"].strftime("%d/%m")
    n = cruce["dias"]
    plazo = "mañana" if n <= 1 else f"en {n} días"
    return (f"Proyección: cruzaría el umbral {plazo} "
            f"({cuando}), con {cruce['au_real_mm']:.0f} mm "
            f"({cruce['pct_au']:.0f} %). Lluvia esperada en el período: "
            f"{lluvia:.0f} mm.")
