"""
clima_agera5.py
----------------
Reemplaza ERA5-Land (GEE) por el dataset AgERA5 del Copernicus Climate Data
Store (CDS): "sis-agrometeorological-indicators". Este dataset ya trae, listas
para usar, precipitación diaria y evapotranspiración de referencia (FAO
Penman-Monteith) a 0.1° (~10 km) de resolución, así que no hace falta
calcular ETo a mano como con ERA5-Land crudo.

Requiere:
  - Cuenta en https://cds.climate.copernicus.eu/
  - Aceptar los términos del dataset "sis-agrometeorological-indicators"
    (se hacen una vez, desde la web del dataset).
  - Un archivo ~/.cdsapirc (en Windows: C:\\Users\\<usuario>\\.cdsapirc) con:
        url: https://cds.climate.copernicus.eu/api
        key: <tu API key personal>

El cuerpo exacto de la request a la API (nombres de variables, versión del
dataset, etc.) puede cambiar con el tiempo del lado de Copernicus. Por eso
NO está hardcodeado en el código: se arma en config.yaml (clave
"cds.request_template") copiando el fragmento que la propia web del dataset
genera en su botón "Show API request" — así, si Copernicus cambia algo, se
actualiza el config sin tocar este script.
"""
from __future__ import annotations

import glob
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)

DATASET = "sis-agrometeorological-indicators"


def _fechas_a_ymd(fechas: Iterable[pd.Timestamp]):
    fechas = pd.DatetimeIndex(fechas)
    years = sorted({f"{d.year:04d}" for d in fechas})
    months = sorted({f"{d.month:02d}" for d in fechas})
    days = sorted({f"{d.day:02d}" for d in fechas})
    return years, months, days


def descargar_agera5(
    fecha_inicio: str,
    fecha_fin: str,
    bbox_wsen: tuple[float, float, float, float],
    request_template: dict,
    cdsapi_rc_path: str | None = None,
) -> pd.DataFrame:
    """Descarga precipitación y ETo (AgERA5) para el rango de fechas y bbox
    dados, y devuelve un DataFrame diario (fecha, precipitacion_mm, eto_mm)
    promediado espacialmente sobre el bbox del lote.

    Parameters
    ----------
    bbox_wsen: (west, south, east, north) -- igual a aoi["bbox"]
    request_template: dict base copiado del "Show API request" de la web del
        dataset (variables, version, etc.); este código completa/sobrescribe
        year/month/day/area/format automáticamente.
    """
    import cdsapi
    import xarray as xr

    west, south, east, north = bbox_wsen
    # AgERA5 es de resolución ~0.1°; se agrega un margen chico para asegurar
    # que el bbox del lote caiga dentro de al menos una celda con datos.
    margen = 0.15
    area = [north + margen, west - margen, south - margen, east + margen]  # [N, W, S, E]

    fechas = pd.date_range(fecha_inicio, fecha_fin, freq="D")
    years, months, days = _fechas_a_ymd(fechas)

    request = dict(request_template)  # no mutar el original
    request["year"] = years
    request["month"] = months
    request["day"] = days
    request["area"] = area

    # Credenciales del CDS: se toman, en este orden de prioridad,
    #   1. variables de entorno CDSAPI_URL / CDSAPI_KEY  (usado en GitHub Actions)
    #   2. archivo ~/.cdsapirc                            (usado en la PC local)
    import os

    cds_url = os.environ.get("CDSAPI_URL")
    cds_key = os.environ.get("CDSAPI_KEY")
    if cds_url and cds_key:
        logger.info("Usando credenciales de CDS desde variables de entorno.")
        client = cdsapi.Client(url=cds_url, key=cds_key)
    else:
        logger.info("Usando credenciales de CDS desde ~/.cdsapirc")
        client = cdsapi.Client()

    with tempfile.TemporaryDirectory() as tmpdir:
        target_zip = Path(tmpdir) / "agera5.zip"
        logger.info("Solicitando AgERA5 a CDS: %s a %s, bbox=%s", fecha_inicio, fecha_fin, area)
        client.retrieve(DATASET, request, str(target_zip))

        extract_dir = Path(tmpdir) / "extraido"
        extract_dir.mkdir()
        if zipfile.is_zipfile(target_zip):
            with zipfile.ZipFile(target_zip) as zf:
                zf.extractall(extract_dir)
        else:
            # Algunos requests devuelven un único NetCDF sin zip
            shutil.copy(target_zip, extract_dir / "agera5.nc")

        nc_files = sorted(glob.glob(str(extract_dir / "*.nc")))
        if not nc_files:
            raise RuntimeError("La descarga de AgERA5 no contiene archivos NetCDF esperados.")

        series = {}
        for nc_path in nc_files:
            ds = xr.open_dataset(nc_path)
            var_name = list(ds.data_vars)[0]
            # Promedio espacial sobre el bbox (resolución ~10km, lote << celda)
            lat_dim = "lat" if "lat" in ds.dims else "latitude"
            lon_dim = "lon" if "lon" in ds.dims else "longitude"
            serie = ds[var_name].mean(dim=[lat_dim, lon_dim]).to_series()
            serie.index = pd.to_datetime(serie.index).normalize()
            clave = "precipitacion_mm" if "precipitation" in var_name.lower() else "eto_mm"
            series[clave] = serie
            ds.close()

    df = pd.DataFrame(series)
    df.index.name = "fecha"
    df = df.reset_index()

    for col in ("precipitacion_mm", "eto_mm"):
        if col not in df.columns:
            logger.warning("No se encontró variable '%s' en la respuesta de AgERA5.", col)
            df[col] = pd.NA

    return df[["fecha", "precipitacion_mm", "eto_mm"]]
