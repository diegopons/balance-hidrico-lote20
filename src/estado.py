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

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

from .balance import EstadoBalance

logger = logging.getLogger(__name__)


def huella_corrida(geojson_aoi: dict, fecha_siembra: str) -> str:
    """Identifica la combinación lote + fecha de siembra.

    Si cambia el polígono o la fecha de siembra, el balance acumulado de
    antes ya no corresponde: hay que empezar de cero. Guardamos esta huella
    junto al estado para poder detectarlo solos, en lugar de depender de
    que alguien se acuerde de borrar estado.json a mano.
    """
    material = json.dumps(geojson_aoi, sort_keys=True) + "|" + str(fecha_siembra)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def cargar_estado(
    path_estado: str | Path,
    au_real_inicial: float,
    prof_raiz_inicial: float,
    huella: str | None = None,
    reiniciar: bool = False,
) -> EstadoBalance:
    """Carga el estado previo, o arranca de cero.

    Arranca de cero cuando: no hay archivo, `reiniciar` es True, o la huella
    guardada no coincide con la actual (cambió el lote o la fecha de siembra).
    """
    path_estado = Path(path_estado)

    if reiniciar and path_estado.exists():
        logger.warning("Se pidió reiniciar el estado: se descarta el balance acumulado.")
        path_estado.unlink()

    if path_estado.exists():
        with open(path_estado, "r", encoding="utf-8") as f:
            data = json.load(f)
        huella_guardada = data.pop("huella", None)

        if huella is not None and huella_guardada is not None and huella_guardada != huella:
            logger.warning(
                "⚠️  Cambió el lote o la fecha de siembra (huella %s -> %s). "
                "El balance acumulado no corresponde: se reinicia desde cero.",
                huella_guardada,
                huella,
            )
        elif huella is not None and huella_guardada is None:
            logger.info("Estado previo sin huella; se adopta la actual y se continúa.")
            logger.info("Estado previo cargado: %s", data)
            return EstadoBalance.from_dict(data)
        else:
            logger.info("Estado previo cargado: %s", data)
            return EstadoBalance.from_dict(data)

    logger.info(
        "Se inicializa el balance: AU=%.1f mm, profundidad de raíz=%.0f cm.",
        au_real_inicial,
        prof_raiz_inicial,
    )
    return EstadoBalance.inicial(au_real_inicial, prof_raiz_inicial)


def guardar_estado(
    path_estado: str | Path, estado: EstadoBalance, huella: str | None = None
) -> None:
    path_estado = Path(path_estado)
    path_estado.parent.mkdir(parents=True, exist_ok=True)
    data = estado.to_dict()
    if huella is not None:
        data["huella"] = huella
    with open(path_estado, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


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
