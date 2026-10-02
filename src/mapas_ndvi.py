"""
mapas_ndvi.py
-------------
Genera un mosaico de imágenes NDVI del lote: una miniatura por fecha con
pasada útil, para ver la evolución espacial del cultivo de un vistazo.

Por qué un mosaico y no un visor interactivo: las imágenes se generan en el
workflow y se guardan como un único PNG en docs/. Así la página no necesita
credenciales de Copernicus en el navegador, y queda un registro visual de
la campaña versionado junto al resto.

Usa la Process API de Copernicus Data Space (distinta de la Statistical API
que calcula la serie de números): devuelve la imagen recortada al polígono.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime

import requests

from .auth_cdse import obtener_token

logger = logging.getLogger(__name__)

PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Paleta del NDVI: de suelo desnudo a canopeo pleno. Son los cortes de uso
# corriente en agricultura; el marrón-amarillo-verde se lee sin leyenda.
EVALSCRIPT_IMAGEN = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: { bands: 4 }
  };
}

function colorNDVI(v) {
  if (v < 0.1)  return [0.65, 0.57, 0.47];   // suelo desnudo
  if (v < 0.2)  return [0.80, 0.72, 0.50];
  if (v < 0.3)  return [0.88, 0.82, 0.45];
  if (v < 0.4)  return [0.80, 0.82, 0.35];
  if (v < 0.5)  return [0.63, 0.76, 0.30];
  if (v < 0.6)  return [0.45, 0.68, 0.27];
  if (v < 0.7)  return [0.28, 0.58, 0.24];
  if (v < 0.8)  return [0.15, 0.47, 0.20];
  return [0.05, 0.35, 0.15];                  // canopeo pleno
}

function evaluatePixel(sample) {
  if (sample.dataMask === 0) return [0, 0, 0, 0];      // fuera del lote

  var scl = sample.SCL;
  var invalida = (scl == 3 || scl == 8 || scl == 9 || scl == 10 || scl == 11);
  if (invalida) return [0.78, 0.80, 0.84, 1];          // nube/sombra: gris

  var ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04 + 1e-9);
  var c = colorNDVI(ndvi);
  return [c[0], c[1], c[2], 1];
}
"""


def _descargar_imagen(token, geojson_geometry, fecha, ancho=256, alto=256):
    """Pide a la Process API la imagen NDVI del lote para un día."""
    payload = {
        "input": {
            "bounds": {
                "geometry": geojson_geometry,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{fecha}T00:00:00Z",
                            "to": f"{fecha}T23:59:59Z",
                        }
                    },
                }
            ],
        },
        "output": {
            "width": ancho,
            "height": alto,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": EVALSCRIPT_IMAGEN,
    }

    r = requests.post(
        PROCESS_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "image/png"},
        json=payload,
        timeout=90,
    )
    if r.status_code != 200:
        logger.warning("  %s: no se pudo obtener la imagen (%s)", fecha, r.status_code)
        return None
    return r.content


def generar_mosaico(
    client_id: str,
    client_secret: str,
    geojson_geometry: dict,
    fechas: list,
    destino: str,
    columnas: int = 4,
    lado_px: int = 220,
    titulo: str = "",
) -> bool:
    """Arma un PNG con una miniatura de NDVI por fecha.

    `fechas` son las fechas con imagen útil (las que la serie detectó como
    observaciones reales), de la más vieja a la más nueva. Se toman las
    últimas hasta completar la grilla.

    Devuelve True si se generó el archivo.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow no está instalado: no se genera el mosaico de NDVI.")
        return False

    if not fechas:
        logger.info("No hay fechas con imagen para el mosaico.")
        return False

    token = obtener_token(client_id, client_secret)

    # últimas N fechas, en orden cronológico
    maximo = columnas * 2  # dos filas
    seleccion = fechas[-maximo:]

    logger.info("Generando mosaico de NDVI con %d fechas...", len(seleccion))

    miniaturas = []
    for f in seleccion:
        datos = _descargar_imagen(token, geojson_geometry, f, lado_px, lado_px)
        if datos:
            try:
                miniaturas.append((f, Image.open(io.BytesIO(datos)).convert("RGBA")))
            except Exception as e:  # noqa: BLE001
                logger.warning("  %s: imagen ilegible (%s)", f, e)

    if not miniaturas:
        logger.warning("No se pudo descargar ninguna imagen para el mosaico.")
        return False

    # --- composición ---
    margen, alto_etiqueta, sep, alto_leyenda = 16, 26, 10, 42
    filas = (len(miniaturas) + columnas - 1) // columnas
    cols = min(columnas, len(miniaturas))
    alto_titulo = 34 if titulo else 0

    ancho_total = margen * 2 + cols * lado_px + (cols - 1) * sep
    alto_total = (
        margen * 2 + alto_titulo + alto_leyenda
        + filas * (lado_px + alto_etiqueta) + (filas - 1) * sep
    )

    lienzo = Image.new("RGB", (ancho_total, alto_total), (245, 246, 241))
    dibujo = ImageDraw.Draw(lienzo)

    try:
        fuente = ImageFont.truetype("DejaVuSans.ttf", 13)
        fuente_titulo = ImageFont.truetype("DejaVuSans-Bold.ttf", 16)
    except OSError:
        fuente = fuente_titulo = ImageFont.load_default()

    if titulo:
        dibujo.text((margen, margen - 2), titulo, fill=(42, 46, 39), font=fuente_titulo)

    for i, (fecha, img) in enumerate(miniaturas):
        fila, col = divmod(i, columnas)
        x = margen + col * (lado_px + sep)
        y = margen + alto_titulo + fila * (lado_px + alto_etiqueta + sep)

        if img.size != (lado_px, lado_px):
            img = img.resize((lado_px, lado_px), Image.NEAREST)

        # fondo claro bajo la imagen: el lote es transparente fuera del polígono
        lienzo.paste(Image.new("RGB", (lado_px, lado_px), (232, 234, 229)), (x, y))
        lienzo.paste(img, (x, y), img)
        dibujo.rectangle([x, y, x + lado_px - 1, y + lado_px - 1],
                         outline=(199, 204, 192))

        try:
            etiqueta = datetime.strptime(fecha, "%Y-%m-%d").strftime("%d/%m")
        except ValueError:
            etiqueta = fecha
        dibujo.text((x + 2, y + lado_px + 5), etiqueta,
                    fill=(107, 113, 102), font=fuente)

    # --- leyenda: sin esto los colores no se pueden leer ---
    escala = [
        ((0.65, 0.57, 0.47), "0.1"),
        ((0.80, 0.72, 0.50), "0.2"),
        ((0.88, 0.82, 0.45), "0.3"),
        ((0.80, 0.82, 0.35), "0.4"),
        ((0.63, 0.76, 0.30), "0.5"),
        ((0.45, 0.68, 0.27), "0.6"),
        ((0.28, 0.58, 0.24), "0.7"),
        ((0.15, 0.47, 0.20), "0.8"),
        ((0.05, 0.35, 0.15), ""),
    ]
    ancho_casilla, alto_casilla = 34, 12
    x0 = margen
    y0 = alto_total - margen - alto_leyenda + 6

    dibujo.text((x0, y0 - 2), "NDVI", fill=(107, 113, 102), font=fuente)
    x0 += 42
    for color, etiqueta in escala:
        dibujo.rectangle(
            [x0, y0, x0 + ancho_casilla, y0 + alto_casilla],
            fill=tuple(int(c * 255) for c in color),
        )
        if etiqueta:
            dibujo.text((x0 + ancho_casilla - 7, y0 + alto_casilla + 3), etiqueta,
                        fill=(107, 113, 102), font=fuente)
        x0 += ancho_casilla

    # el gris de nube se explica aparte: no es un valor de la escala
    x0 += 26
    dibujo.rectangle([x0, y0, x0 + ancho_casilla, y0 + alto_casilla],
                     fill=(199, 204, 214))
    dibujo.text((x0 + ancho_casilla + 8, y0 - 1), "nube o sombra",
                fill=(107, 113, 102), font=fuente)

    lienzo.save(destino, "PNG", optimize=True)
    logger.info("Mosaico guardado en %s (%d fechas).", destino, len(miniaturas))
    return True
