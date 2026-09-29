"""
ndvi_sentinelhub.py
--------------------
Reemplaza la extracción de NDVI que antes se hacía en Google Earth Engine
(Sentinel-2 + Landsat + MODIS fusionados) por la Statistical API de
Copernicus Data Space Ecosystem, usando únicamente Sentinel-2 L2A (10 m).

La Statistical API calcula estadísticas (media, etc.) directamente en el
servidor sobre el polígono del lote, sin descargar imágenes completas —
es la forma correcta y liviana de sacar una serie temporal de un índice
para un AOI chico.

El enmascarado de nubes/sombras/nieve se hace vía la banda SCL (Scene
Classification Layer) de Sentinel-2 L2A dentro del evalscript.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import requests

from .auth_cdse import obtener_token

logger = logging.getLogger(__name__)

STATISTICS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

# Evalscript: calcula NDVI y devuelve además una máscara de validez (dataMask)
# que excluye nubes (8,9,10), cirros, sombra de nubes (3) y nieve (11) según
# la clasificación SCL de Sentinel-2 L2A. La Statistical API usa la banda
# "dataMask" del output para decidir qué píxeles entran en las estadísticas.
EVALSCRIPT_NDVI = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "data", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}

function evaluatePixel(sample) {
  var scl = sample.SCL;
  // Clases SCL a excluir: 3 sombra de nube, 8/9 nube media/alta prob.,
  // 10 cirros delgados, 11 nieve/hielo.
  var invalida = (scl == 3 || scl == 8 || scl == 9 || scl == 10 || scl == 11);
  var ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04 + 1e-9);
  var mascara = invalida ? 0 : sample.dataMask;
  return {
    data: [ndvi],
    dataMask: [mascara]
  };
}
"""


def obtener_serie_ndvi(
    client_id: str,
    client_secret: str,
    geojson_geometry: dict,
    fecha_inicio: str,
    fecha_fin: str,
    max_cloud_coverage: int = 60,
    resolucion_m: int = 10,
) -> pd.DataFrame:
    """Devuelve un DataFrame diario (fecha, ndvi) para el rango solicitado.

    Los días sin pasada de Sentinel-2 (o completamente nublados) quedan con
    ndvi = NaN; el arrastre (ffill) se resuelve más adelante, en el módulo de
    balance, para no perder información sobre qué días son realmente datos
    satelitales vs. arrastrados.
    """
    token = obtener_token(client_id, client_secret)

    payload = {
        "input": {
            "bounds": {
                "geometry": geojson_geometry,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {"maxCloudCoverage": max_cloud_coverage},
                }
            ],
        },
        "aggregation": {
            "timeRange": {
                "from": f"{fecha_inicio}T00:00:00Z",
                "to": f"{fecha_fin}T23:59:59Z",
            },
            "aggregationInterval": {"of": "P1D"},
            "evalscript": EVALSCRIPT_NDVI,
            "resx": resolucion_m,
            "resy": resolucion_m,
        },
        "calculations": {"default": {}},
    }

    resp = requests.post(
        STATISTICS_URL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Error consultando Statistical API de CDSE ({resp.status_code}): {resp.text}"
        )

    body = resp.json()
    filas = []
    for intervalo in body.get("data", []):
        fecha_str = intervalo["interval"]["from"][:10]
        try:
            stats = intervalo["outputs"]["data"]["bands"]["B0"]["stats"]
        except KeyError:
            continue
        sample_count = stats.get("sampleCount", 0)
        nodata_count = stats.get("noDataCount", 0)
        if sample_count - nodata_count <= 0:
            ndvi_val = None  # día sin píxeles válidos (100% nublado, sin pasada, etc.)
        else:
            ndvi_val = stats.get("mean")
        filas.append({"fecha": fecha_str, "ndvi": ndvi_val})

    df = pd.DataFrame(filas)
    if df.empty:
        df = pd.DataFrame(columns=["fecha", "ndvi"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


if __name__ == "__main__":
    # Prueba manual rápida (requiere credenciales reales en variables de entorno)
    import os
    import sys
    import json as _json

    logging.basicConfig(level=logging.INFO)
    cid = os.environ["CDSE_CLIENT_ID"]
    csec = os.environ["CDSE_CLIENT_SECRET"]
    geom = _json.load(open(sys.argv[1]))
    hoy = date.today()
    df = obtener_serie_ndvi(cid, csec, geom, str(hoy - timedelta(days=20)), str(hoy - timedelta(days=5)))
    print(df)
