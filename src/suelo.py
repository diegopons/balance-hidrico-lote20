"""
suelo.py
--------
Traducción a Python de la hoja "SUELO" de la planilla Excel (BH p-Pons.xlsx,
serie "Los llanos - Serie Oncativo") y de la lógica ya usada en el notebook
balance_hidrico_gee (v6). Se mantiene igual para no romper continuidad con
los cálculos históricos ya validados.
"""
from __future__ import annotations

from typing import List, Dict

import pandas as pd


def precalcular_parametros_suelo(propiedades_suelo: List[Dict]) -> pd.DataFrame:
    """Convierte % CC / % PMP por capa en mm acumulados y Agua Útil Máxima (AU Max)."""
    perfil = []
    cc_acum_mm = 0.0
    pmp_acum_mm = 0.0
    prof_anterior = 0

    for capa in propiedades_suelo:
        espesor_mm = (capa["prof_hasta_cm"] - prof_anterior) * 10
        cc_mm = (capa["cc_porcentaje"] / 100) * capa["densidad_aparente"] * espesor_mm
        pmp_mm = (capa["pmp_porcentaje"] / 100) * capa["densidad_aparente"] * espesor_mm
        cc_acum_mm += cc_mm
        pmp_acum_mm += pmp_mm
        au_max_acum = cc_acum_mm - pmp_acum_mm

        perfil.append(
            {
                "prof_cm": capa["prof_hasta_cm"],
                "cc_acum_mm": cc_acum_mm,
                "pmp_acum_mm": pmp_acum_mm,
                "au_max_acum_mm": au_max_acum,
            }
        )
        prof_anterior = capa["prof_hasta_cm"]

    return pd.DataFrame(perfil)


def obtener_au_max_para_profundidad(profundidad_raiz_cm: float, df_suelo: pd.DataFrame) -> float:
    """Equivalente al BUSCARV() de Excel: AU Max acumulada hasta la profundidad de raíz actual."""
    if profundidad_raiz_cm <= df_suelo["prof_cm"].min():
        primera_capa = df_suelo.iloc[0]
        proporcion = profundidad_raiz_cm / primera_capa["prof_cm"]
        return max(primera_capa["au_max_acum_mm"] * proporcion, 10.0)
    capa_correspondiente = df_suelo[df_suelo["prof_cm"] >= profundidad_raiz_cm].iloc[0]
    return capa_correspondiente["au_max_acum_mm"]


# Valores por defecto = serie "Los llanos - Serie Oncativo" de BH p-Pons.xlsx.
# Se pueden sobrescribir desde config.yaml (clave "suelo") sin tocar este archivo.
SUELO_PROPIEDADES_DEFAULT = [
    {"prof_hasta_cm": 20, "cc_porcentaje": 26.8, "pmp_porcentaje": 10.5, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 40, "cc_porcentaje": 22.8, "pmp_porcentaje": 9.4, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 60, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 80, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 100, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 120, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 140, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 160, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 180, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 200, "cc_porcentaje": 21.5, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
]
