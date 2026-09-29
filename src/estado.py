"""
estado.py
---------
Persistencia entre corridas del script:
  - estado.json  -> último día procesado, AU real y profundidad de raíz
                     al cierre de esa corrida (para continuar mañana/la
                     próxima semana sin recalcular toda la temporada).
  - <salida>.csv -> serie histórica completa de resultados diarios
                     (se va agregando fila por fila en cada corrida).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from .balance import EstadoBalance

logger = logging.getLogger(__name__)


def cargar_estado(path_estado: str | Path, au_real_inicial: float, prof_raiz_inicial: float) -> EstadoBalance:
    path_estado = Path(path_estado)
    if path_estado.exists():
        with open(path_estado, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Estado previo cargado: %s", data)
        return EstadoBalance.from_dict(data)
    logger.info(
        "No hay estado previo. Se inicializa AU=%.1f mm, profundidad de raíz=%.0f cm.",
        au_real_inicial,
        prof_raiz_inicial,
    )
    return EstadoBalance.inicial(au_real_inicial, prof_raiz_inicial)


def guardar_estado(path_estado: str | Path, estado: EstadoBalance) -> None:
    path_estado = Path(path_estado)
    path_estado.parent.mkdir(parents=True, exist_ok=True)
    with open(path_estado, "w", encoding="utf-8") as f:
        json.dump(estado.to_dict(), f, indent=2, ensure_ascii=False, default=str)


def append_resultados_csv(path_csv: str | Path, df_nuevos: pd.DataFrame) -> None:
    """Agrega filas nuevas al CSV histórico, sin duplicar fechas ya guardadas."""
    path_csv = Path(path_csv)
    path_csv.parent.mkdir(parents=True, exist_ok=True)

    if df_nuevos.empty:
        return

    if path_csv.exists():
        df_previo = pd.read_csv(path_csv, parse_dates=["fecha"])
        df_final = pd.concat([df_previo, df_nuevos], ignore_index=True)
        df_final = df_final.drop_duplicates(subset="fecha", keep="last")
        df_final = df_final.sort_values("fecha")
    else:
        df_final = df_nuevos.sort_values("fecha")

    df_final.to_csv(path_csv, index=False)
    logger.info("CSV actualizado: %s (%d filas totales)", path_csv, len(df_final))
