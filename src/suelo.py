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


def precalcular_parametros_suelo(
    propiedades_suelo: List[Dict],
    llenado_inicial_pct: float = 70.0,
) -> pd.DataFrame:
    """Convierte % CC / % PMP por capa en mm acumulados y Agua Útil Máxima (AU Max).

    Además calcula, por capa, el agua útil ALMACENADA al inicio de la campaña.
    Ese dato hace falta para la recarga que ocurre cuando la raíz alcanza una
    capa nueva: hasta ese momento el agua de esa capa está en el perfil pero
    fuera del alcance del cultivo, y al llegar la raíz se vuelve disponible.

    Cada capa puede traer `agua_inicial_mm` (lo medido en la calicata) o
    `llenado_inicial_pct` propio. Si no trae ninguno se usa el
    `llenado_inicial_pct` general, que es una suposición: conviene cargar los
    valores de calicata cuando se tengan.
    """
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
        au_capa_mm = cc_mm - pmp_mm

        if capa.get("agua_inicial_mm") is not None:
            agua_inicial = float(capa["agua_inicial_mm"])
        else:
            pct = capa.get("llenado_inicial_pct", llenado_inicial_pct)
            agua_inicial = au_capa_mm * (float(pct) / 100.0)
        agua_inicial = max(0.0, min(agua_inicial, au_capa_mm))

        perfil.append(
            {
                "prof_cm": capa["prof_hasta_cm"],
                "prof_desde_cm": prof_anterior,
                "cc_acum_mm": cc_acum_mm,
                "pmp_acum_mm": pmp_acum_mm,
                "au_max_acum_mm": au_max_acum,
                "au_capa_mm": au_capa_mm,
                "agua_inicial_capa_mm": agua_inicial,
            }
        )
        prof_anterior = capa["prof_hasta_cm"]

    return pd.DataFrame(perfil)


def agua_de_capas_alcanzadas(
    prof_antes_cm: float, prof_despues_cm: float, df_suelo: pd.DataFrame
) -> float:
    """Agua útil almacenada en las capas que la raíz alcanza al profundizar.

    Equivale al término `SUELO!L<fila>` que la planilla BH p-Pons suma el día
    en que la raíz entra en una capa nueva. Una capa se cuenta cuando la raíz
    cruza su límite superior, que es el mismo criterio con el que
    `obtener_au_max_para_profundidad` la incorpora al agua útil máxima; así
    cada capa aporta una sola vez y el agua almacenada entra junto con el
    espacio que esa capa agrega.
    """
    if prof_despues_cm <= prof_antes_cm or "agua_inicial_capa_mm" not in df_suelo:
        return 0.0
    nuevas = df_suelo[
        (df_suelo["prof_desde_cm"] < prof_despues_cm)
        & (df_suelo["prof_desde_cm"] >= prof_antes_cm)
    ]
    return float(nuevas["agua_inicial_capa_mm"].sum())


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
    {"prof_hasta_cm": 140, "cc_porcentaje": 21.0, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 160, "cc_porcentaje": 21.0, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 180, "cc_porcentaje": 21.0, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
    {"prof_hasta_cm": 200, "cc_porcentaje": 21.0, "pmp_porcentaje": 9.2, "densidad_aparente": 1.25},
]
