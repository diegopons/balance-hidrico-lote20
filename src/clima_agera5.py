"""
clima_agera5.py
----------------
Descarga precipitación y evapotranspiración de referencia (ETo) del dataset
AgERA5 del Copernicus Climate Data Store.

IMPORTANTE: el dataset acepta UNA variable por pedido. Por eso este módulo
hace una descarga por variable y después las junta. (Pedir las dos juntas
devuelve en silencio un solo archivo, y el balance se queda sin ETo.)

Credenciales: variables de entorno CDSAPI_URL / CDSAPI_KEY, o ~/.cdsapirc
"""
from __future__ import annotations

import glob
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)

DATASET = "sis-agrometeorological-indicators"

# Palabras clave para reconocer qué trae cada archivo descargado
CLAVES = [
    ("precipitacion_mm", ("precipitation", "precip")),
    ("eto_mm", ("evapotranspiration", "evapo", "eto", "et0")),
]


def _fechas_a_ymd(fechas: Iterable[pd.Timestamp]):
    fechas = pd.DatetimeIndex(fechas)
    years = sorted({f"{d.year:04d}" for d in fechas})
    months = sorted({f"{d.month:02d}" for d in fechas})
    days = sorted({f"{d.day:02d}" for d in fechas})
    return years, months, days


def _cliente_cds():
    import cdsapi

    url = os.environ.get("CDSAPI_URL")
    key = os.environ.get("CDSAPI_KEY")
    if url and key:
        logger.info("Usando credenciales de CDS desde variables de entorno.")
        return cdsapi.Client(url=url, key=key)
    logger.info("Usando credenciales de CDS desde ~/.cdsapirc")
    return cdsapi.Client()


def _clasificar(texto: str) -> str | None:
    texto = texto.lower()
    for clave, palabras in CLAVES:
        if any(p in texto for p in palabras):
            return clave
    return None


def _descargar_una_variable(client, variable, request_base, years, months, days, area):
    """Pide UNA variable y devuelve (clave, serie) o (None, None) si no vino."""
    import xarray as xr

    request = dict(request_base)
    request.pop("variable", None)
    request["variable"] = [variable] if isinstance(variable, str) else list(variable)
    request["year"] = years
    request["month"] = months
    request["day"] = days
    request["area"] = area

    with tempfile.TemporaryDirectory() as tmpdir:
        destino = Path(tmpdir) / "descarga.zip"
        logger.info("Pidiendo a AgERA5 la variable '%s'...", variable)
        client.retrieve(DATASET, request, str(destino))

        extraido = Path(tmpdir) / "extraido"
        extraido.mkdir()
        if zipfile.is_zipfile(destino):
            with zipfile.ZipFile(destino) as zf:
                zf.extractall(extraido)
        else:
            shutil.copy(destino, extraido / "datos.nc")

        nc_files = sorted(glob.glob(str(extraido / "*.nc")))
        logger.info(
            "  archivos recibidos para '%s': %s",
            variable,
            [Path(p).name for p in nc_files],
        )
        if not nc_files:
            logger.warning("  no se recibió NetCDF para '%s'", variable)
            return None, None

        series_var = []
        clave = None
        for nc_path in nc_files:
            ds = xr.open_dataset(nc_path)
            var_name = list(ds.data_vars)[0]
            logger.info("  %s -> %s", Path(nc_path).name, list(ds.data_vars))

            clave = _clasificar(var_name) or _clasificar(Path(nc_path).name) or _clasificar(str(variable))
            lat_dim = "lat" if "lat" in ds.dims else "latitude"
            lon_dim = "lon" if "lon" in ds.dims else "longitude"
            serie = ds[var_name].mean(dim=[lat_dim, lon_dim]).to_series()
            serie.index = pd.to_datetime(serie.index).normalize()
            series_var.append(serie)
            ds.close()

        if clave is None:
            logger.warning("  no se pudo clasificar la variable '%s'", variable)
            return None, None

        return clave, pd.concat(series_var).sort_index()


def descargar_agera5(
    fecha_inicio: str,
    fecha_fin: str,
    bbox_wsen: tuple[float, float, float, float],
    request_template: dict,
    cdsapi_rc_path: str | None = None,
) -> pd.DataFrame:
    """Devuelve un DataFrame diario (fecha, precipitacion_mm, eto_mm)."""
    west, south, east, north = bbox_wsen
    margen = 0.15
    area = [north + margen, west - margen, south - margen, east + margen]

    fechas = pd.date_range(fecha_inicio, fecha_fin, freq="D")
    years, months, days = _fechas_a_ymd(fechas)

    variables = request_template.get("variable", [])
    if isinstance(variables, str):
        variables = [variables]
    if not variables:
        raise ValueError("config.yaml: cds.request_template no define 'variable'.")

    client = _cliente_cds()

    series = {}
    for variable in variables:
        clave, serie = _descargar_una_variable(
            client, variable, request_template, years, months, days, area
        )
        if clave and serie is not None:
            series[clave] = serie

    if not series:
        raise RuntimeError("AgERA5 no devolvió ninguna variable utilizable.")

    df = pd.DataFrame(series)
    df.index.name = "fecha"
    df = df.reset_index()

    for col in ("precipitacion_mm", "eto_mm"):
        if col not in df.columns:
            logger.warning(
                "⚠️  Falta '%s' en la respuesta de AgERA5. El balance quedará "
                "incompleto: revisá los nombres de variable en config.yaml.",
                col,
            )
            df[col] = pd.NA

    logger.info(
        "AgERA5: %d días, precipitación %s, ETo %s",
        len(df),
        "OK" if df["precipitacion_mm"].notna().any() else "FALTA",
        "OK" if df["eto_mm"].notna().any() else "FALTA",
    )

    return df[["fecha", "precipitacion_mm", "eto_mm"]]
