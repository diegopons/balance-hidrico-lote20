#!/usr/bin/env python3
"""
Prueba las fuentes de clima y las compara entre sí, sin tocar el estado, el CSV
ni Telegram.

    python probar_clima.py            # últimos 30 días
    python probar_clima.py 90         # últimos 90 días

Sirve para dos cosas: confirmar que cada fuente responde desde esta máquina, y
ver cuánto se parecen entre sí sobre el mismo lote y el mismo período. Si no
coinciden, el que manda es el pluviómetro de la estación.
"""
import logging
import sys

import numpy as np
import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from src.aoi import cargar_aoi  # noqa: E402
from src import clima as mod_clima  # noqa: E402


def intentar(nombre, funcion):
    try:
        return funcion(), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def main() -> int:
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    aoi = cargar_aoi(cfg["aoi"]["archivo"])
    bbox = aoi["bbox"]

    hoy = pd.Timestamp.today().normalize()
    desde = (hoy - pd.Timedelta(days=dias)).strftime("%Y-%m-%d")
    hasta = hoy.strftime("%Y-%m-%d")

    print(f"\nLote: {aoi['area_ha']:.2f} ha   período {desde} a {hasta}\n")

    fuentes, estacion = mod_clima.armar_fuentes(cfg, bbox, desde, hasta)
    series = {}

    for nombre, obtener in fuentes:
        print(f"--- {nombre} " + "-" * (60 - len(nombre)))
        df, error = intentar(nombre, obtener)
        if error:
            print(f"  NO DISPONIBLE: {error}\n")
            continue
        df = df.copy()
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.normalize()
        series[nombre] = df.set_index("fecha")
        ultimo = df["fecha"].max()
        print(f"  {len(df)} días, hasta {ultimo.date()} "
              f"(rezago {(hoy - ultimo).days} día/s)")
        print(f"  lluvia {df['precipitacion_mm'].sum():.1f} mm   "
              f"ETo {df['eto_mm'].sum():.1f} mm")
        if nombre == "siga" and estacion:
            print(f"  estación: {estacion.get('nombre')} "
                  f"({estacion.get('id_interno')}) a {estacion.get('km', 0):.2f} km")
        print()

    if len(series) >= 2:
        print("--- comparación entre fuentes " + "-" * 31)
        nombres = list(series)
        ref = nombres[0]
        for otro in nombres[1:]:
            com = series[ref].join(series[otro], how="inner",
                                   lsuffix="_a", rsuffix="_b").dropna()
            if com.empty:
                print(f"  {ref} vs {otro}: sin días en común\n")
                continue
            for var, et in (("precipitacion_mm", "lluvia"), ("eto_mm", "ETo")):
                a, b = com[f"{var}_a"].astype(float), com[f"{var}_b"].astype(float)
                dif = (b.sum() / a.sum() - 1) * 100 if a.sum() else float("nan")
                corr = a.corr(b)
                print(f"  {et:7s} {ref} {a.sum():7.1f} mm   {otro} {b.sum():7.1f} mm"
                      f"   ({dif:+.0f} %)   EAM {np.abs(a - b).mean():.2f}"
                      f"   corr {corr:.3f}")
            print(f"           sobre {len(com)} días en común\n")

    print("--- serie combinada " + "-" * 41)
    df, detalle = mod_clima.combinar(fuentes, desde, hasta)
    print("  " + mod_clima.resumen_origen(df))
    if detalle["faltantes"]["precipitacion_mm"] or detalle["faltantes"]["eto_mm"]:
        print(f"  ATENCIÓN, días sin dato: {detalle['faltantes']}")
    print(f"\n  lluvia {pd.to_numeric(df['precipitacion_mm']).sum():.1f} mm   "
          f"ETo {pd.to_numeric(df['eto_mm']).sum():.1f} mm")
    print("\n  últimos 7 días:")
    print(df.tail(7).to_string(index=False))

    if not detalle["usadas"]:
        print("\nNinguna fuente respondió. Revisá la conexión.")
        return 1
    print("\nListo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
