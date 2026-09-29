"""
balance.py
----------
Mismas fórmulas agronómicas del notebook balance_hidrico_gee (v6) / planilla
Excel, pero reorganizadas para correr en modo INCREMENTAL: en cada corrida
periódica solo se procesan los días nuevos, partiendo del estado (AU real y
profundidad de raíz) dejado por la corrida anterior. Esto evita reprocesar
toda la temporada cada vez que se ejecuta el script.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

from .suelo import obtener_au_max_para_profundidad


def calcular_kc_desde_ndvi(ndvi: float, a: float = 1.77, b: float = -0.198) -> float:
    kc = a * ndvi + b
    return max(0.1, min(kc, 1.2))


def calcular_ks(pct_au: float, pct_ur: float) -> float:
    if pct_au >= pct_ur:
        return 1.0
    elif pct_au <= 0:
        return 0.0
    else:
        return pct_au / pct_ur


@dataclass
class EstadoBalance:
    """Estado persistente entre corridas."""
    ultima_fecha_procesada: Optional[str]  # 'YYYY-MM-DD' o None si aún no corrió
    au_real_mm: float
    prof_raiz_cm: float
    ultimo_ndvi_valido: Optional[float] = None  # para rellenar huecos al inicio de una corrida

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EstadoBalance":
        return cls(**d)

    @classmethod
    def inicial(cls, au_real_inicial: float, prof_raiz_inicial: float) -> "EstadoBalance":
        return cls(
            ultima_fecha_procesada=None,
            au_real_mm=au_real_inicial,
            prof_raiz_cm=prof_raiz_inicial,
        )


def procesar_dias_nuevos(
    datos_nuevos: pd.DataFrame,
    estado: EstadoBalance,
    df_suelo: pd.DataFrame,
    umbral_riego_pct: float = 50,
    incremento_raiz_diario_cm: float = 2.0,
    prof_raiz_max_cm: float = 200.0,
    kc_a: float = 1.77,
    kc_b: float = -0.198,
) -> tuple[pd.DataFrame, EstadoBalance]:
    """Corre el balance hídrico día a día sobre `datos_nuevos` (columnas:
    fecha, precipitacion_mm, eto_mm, ndvi, riego_mm) partiendo del `estado`
    recibido, y devuelve (df_resultados_nuevos, estado_actualizado).

    Es exactamente la misma física que `modelo_balance_hidrico()` del
    notebook original, solo que arranca desde un estado guardado en vez de
    desde el día de siembra cada vez.
    """
    resultados = []
    au_real_ayer = estado.au_real_mm
    prof_raiz_actual = estado.prof_raiz_cm
    ultimo_ndvi_valido = estado.ultimo_ndvi_valido

    datos_nuevos = datos_nuevos.sort_values("fecha").reset_index(drop=True)

    for _, dia in datos_nuevos.iterrows():
        prof_raiz_actual = min(prof_raiz_actual + incremento_raiz_diario_cm, prof_raiz_max_cm)
        au_max_dia = obtener_au_max_para_profundidad(prof_raiz_actual, df_suelo)
        au_real_ayer = min(au_real_ayer, au_max_dia)
        pct_au_inicial = (au_real_ayer / au_max_dia) * 100 if au_max_dia > 0 else 0

        ndvi_dia = dia["ndvi"]
        if pd.isna(ndvi_dia):
            # Sin dato satelital ese día (nubes, falta de pasada): se arrastra
            # el último NDVI válido conocido, igual que el ffill del notebook.
            ndvi_dia = ultimo_ndvi_valido if ultimo_ndvi_valido is not None else 0.3
        else:
            ultimo_ndvi_valido = ndvi_dia

        kc = calcular_kc_desde_ndvi(ndvi_dia, kc_a, kc_b)
        eto = dia["eto_mm"] if not pd.isna(dia["eto_mm"]) else 0.0
        etc = eto * kc
        ks = calcular_ks(pct_au_inicial, umbral_riego_pct)
        etc_ajustada = etc * ks

        precipitacion = dia["precipitacion_mm"] if not pd.isna(dia["precipitacion_mm"]) else 0.0
        riego = dia.get("riego_mm", 0.0) or 0.0
        ingresos_agua = precipitacion + riego
        au_real_hoy = au_real_ayer - etc_ajustada + ingresos_agua

        percolacion_profunda = max(0.0, au_real_hoy - au_max_dia)
        au_real_hoy = min(au_real_hoy, au_max_dia)
        au_real_hoy = max(au_real_hoy, 0.0)
        pct_au_final = (au_real_hoy / au_max_dia) * 100 if au_max_dia > 0 else 0

        resultados.append(
            {
                "fecha": dia["fecha"],
                "precipitacion_mm": round(precipitacion, 2),
                "eto_mm": round(eto, 2),
                "ndvi": round(ndvi_dia, 3),
                "prof_raiz_cm": round(prof_raiz_actual, 1),
                "au_max_mm": round(au_max_dia, 2),
                "kc": round(kc, 3),
                "ks": round(ks, 3),
                "etc_ajustada_mm": round(etc_ajustada, 2),
                "percolacion_mm": round(percolacion_profunda, 2),
                "riego_mm": round(riego, 2),
                "au_real_mm": round(au_real_hoy, 2),
                "pct_au": round(pct_au_final, 1),
            }
        )

        au_real_ayer = au_real_hoy

    df_resultados = pd.DataFrame(resultados)

    nuevo_estado = EstadoBalance(
        ultima_fecha_procesada=str(datos_nuevos["fecha"].max().date())
        if len(datos_nuevos) > 0
        else estado.ultima_fecha_procesada,
        au_real_mm=au_real_ayer,
        prof_raiz_cm=prof_raiz_actual,
        ultimo_ndvi_valido=ultimo_ndvi_valido,
    )

    return df_resultados, nuevo_estado
