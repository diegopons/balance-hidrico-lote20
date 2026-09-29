"""
aoi.py
------
Carga el polígono del lote (Área de Interés) desde un Shapefile y lo deja
listo en dos formatos:
    - geometry_wgs84: objeto shapely (EPSG:4326) -> usado para bbox / CDS
    - geojson_geometry: dict GeoJSON (EPSG:4326)   -> usado por la Statistical
      API de Copernicus Data Space Ecosystem (Sentinel Hub)

Se intenta primero con geopandas (camino normal). Si el .dbf viniera dañado
(puede pasar con copias/exportaciones de Drive u otros orígenes) se cae a un
segundo método que lee la geometría directamente con `pyshp`, ignorando los
atributos (no los necesitamos, solo el polígono).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from shapely.geometry import shape, mapping
from shapely.ops import unary_union

logger = logging.getLogger(__name__)


def _cargar_con_geopandas(shp_path: Path):
    import geopandas as gpd

    gdf = gpd.read_file(shp_path)
    if gdf.empty:
        raise ValueError("El shapefile no contiene geometrías.")
    if gdf.crs is None:
        logger.warning("El shapefile no tiene CRS definido; se asume EPSG:4326.")
    elif str(gdf.crs).upper() not in ("EPSG:4326", "OGC:CRS84"):
        gdf = gdf.to_crs("EPSG:4326")
    geom = unary_union(gdf.geometry.values)
    return geom


def _cargar_con_pyshp(shp_path: Path):
    """Fallback: lee solo la geometría (sin atributos) con pyshp.

    Útil cuando el .dbf está corrupto/incompleto pero el .shp/.shx están bien.
    Asume que el .prj ya indica WGS84 (como es el caso de lote_20.prj).
    """
    import shapefile  # pyshp

    shx_path = shp_path.with_suffix(".shx")
    sf = shapefile.Reader(shp=str(shp_path), shx=str(shx_path))
    geoms = []
    for s in sf.shapes():
        geojson_geom = s.__geo_interface__
        geoms.append(shape(geojson_geom))
    if not geoms:
        raise ValueError("No se encontraron geometrías en el .shp")
    return unary_union(geoms)


def cargar_aoi(shp_path: str | Path) -> dict:
    """Devuelve un dict con la geometría del lote en distintos formatos.

    Returns
    -------
    {
        "geometry": shapely.geometry.base.BaseGeometry (EPSG:4326),
        "geojson": dict (GeoJSON geometry, EPSG:4326),
        "bbox": (minx, miny, maxx, maxy)   # lon/lat
        "area_ha": float
    }
    """
    shp_path = Path(shp_path)
    if not shp_path.exists():
        raise FileNotFoundError(f"No se encontró el shapefile: {shp_path}")

    try:
        geom = _cargar_con_geopandas(shp_path)
        logger.info("AOI cargado con geopandas.")
    except Exception as e:  # noqa: BLE001
        logger.warning("Falló la lectura con geopandas (%s). Probando fallback pyshp...", e)
        geom = _cargar_con_pyshp(shp_path)
        logger.info("AOI cargado con pyshp (fallback, sin atributos).")

    # Área aproximada en hectáreas usando una proyección equiareal simple
    # (suficiente para lotes chicos; para mayor precisión usar una UTM local).
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    area_m2 = abs(geod.geometry_area_perimeter(geom)[0])
    area_ha = area_m2 / 10_000

    return {
        "geometry": geom,
        "geojson": mapping(geom),
        "bbox": geom.bounds,  # (minx, miny, maxx, maxy) = (west, south, east, north)
        "area_ha": area_ha,
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    info = cargar_aoi(sys.argv[1] if len(sys.argv) > 1 else "aoi/lote_20.shp")
    print(json.dumps(info["geojson"], indent=2))
    print("BBox (W,S,E,N):", info["bbox"])
    print(f"Área: {info['area_ha']:.2f} ha")
