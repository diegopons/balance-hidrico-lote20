"""
main.py
-------
Orquestador de una corrida periódica del balance hídrico.

Pensado para ser disparado por el Programador de Tareas de Windows (o cron,
o lo que sea) cada N días. Cada corrida:

  1. Lee config.yaml y el estado de la corrida anterior (data/estado.json).
  2. Calcula qué rango de fechas es "nuevo" (desde el día siguiente al
     último procesado, hasta hoy - rezago).
  3. Si no hay días nuevos, no hace nada (log y sale).
  4. Descarga NDVI (Copernicus Data Space Ecosystem) y clima
     (Copernicus Climate Data Store / AgERA5) para ese rango.
  5. Corre el modelo de balance hídrico día a día, partiendo del estado
     anterior.
  6. Agrega los resultados nuevos al CSV histórico y guarda el nuevo estado.
  7. Si el % de Agua Útil final quedó por debajo del umbral de riego, lo
     deja bien visible en el log (alerta de riego).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# Permite ejecutar tanto como módulo (`python -m src.main`) como script directo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.aoi import cargar_aoi
from src.balance import procesar_dias_nuevos
from src.clima_agera5 import descargar_agera5
from src.config import cargar_config
from src.estado import append_resultados_csv, cargar_estado, guardar_estado
from src.ndvi_sentinelhub import obtener_serie_ndvi
from src.notificaciones import armar_mensaje, debe_notificar, enviar_telegram
from src.suelo import SUELO_PROPIEDADES_DEFAULT, precalcular_parametros_suelo


def configurar_logging(log_file: str) -> None:
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )


def main(config_path: str = "config.yaml") -> int:
    cfg = cargar_config(config_path)
    configurar_logging(cfg["rutas"]["log_file"])
    log = logging.getLogger("main")

    log.info("========== Nueva corrida de Balance Hídrico ==========")

    # 1. Credenciales (nunca en config.yaml)
    cdse_client_id = os.environ.get("CDSE_CLIENT_ID")
    cdse_client_secret = os.environ.get("CDSE_CLIENT_SECRET")
    if not cdse_client_id or not cdse_client_secret:
        log.error(
            "Faltan variables de entorno CDSE_CLIENT_ID / CDSE_CLIENT_SECRET. "
            "Ver README.md para cómo crearlas y configurarlas."
        )
        return 1

    # 2. AOI
    aoi_info = cargar_aoi(cfg["aoi"]["shapefile"])
    log.info("Lote cargado: %.2f ha. BBox=%s", aoi_info["area_ha"], aoi_info["bbox"])

    # 3. Estado y suelo
    estado = cargar_estado(
        cfg["rutas"]["estado_json"],
        au_real_inicial=cfg["campana"]["au_real_inicial_mm"],
        prof_raiz_inicial=cfg["campana"]["prof_raiz_inicial_cm"],
    )
    df_suelo = precalcular_parametros_suelo(cfg.get("suelo", SUELO_PROPIEDADES_DEFAULT))

    # 4. Definir rango de fechas nuevo
    if estado.ultima_fecha_procesada:
        fecha_desde = pd.to_datetime(estado.ultima_fecha_procesada) + timedelta(days=1)
    else:
        fecha_desde = pd.to_datetime(cfg["campana"]["fecha_siembra"])

    rezago = max(cfg["rezago_dias"]["ndvi"], cfg["rezago_dias"]["clima"])
    fecha_hasta = pd.to_datetime(date.today()) - timedelta(days=rezago)

    if fecha_desde > fecha_hasta:
        log.info(
            "Nada nuevo para procesar todavía (último día procesado: %s; "
            "próximo disponible recién el %s por el rezago de datos).",
            estado.ultima_fecha_procesada,
            (fecha_desde + timedelta(days=0)).date(),
        )
        return 0

    fecha_desde_str = fecha_desde.strftime("%Y-%m-%d")
    fecha_hasta_str = fecha_hasta.strftime("%Y-%m-%d")
    log.info("Procesando rango nuevo: %s -> %s", fecha_desde_str, fecha_hasta_str)

    # 5. NDVI (Copernicus Data Space Ecosystem)
    log.info("Descargando NDVI (Sentinel-2 / CDSE Statistical API)...")
    df_ndvi = obtener_serie_ndvi(
        cdse_client_id,
        cdse_client_secret,
        aoi_info["geojson"],
        fecha_desde_str,
        fecha_hasta_str,
        max_cloud_coverage=cfg["cdse"]["max_cloud_coverage"],
        resolucion_m=cfg["cdse"]["resolucion_m"],
    )
    log.info(
        "NDVI: %d días con dato válido de %d días del rango.",
        df_ndvi["ndvi"].notna().sum(),
        len(df_ndvi),
    )

    # 6. Clima (Copernicus Climate Data Store / AgERA5)
    log.info("Descargando precipitación y ETo (CDS / AgERA5)...")
    df_clima = descargar_agera5(
        fecha_desde_str,
        fecha_hasta_str,
        aoi_info["bbox"],
        request_template=cfg["cds"]["request_template"],
    )

    # 7. Merge en calendario diario completo del rango
    rango_fechas = pd.date_range(fecha_desde_str, fecha_hasta_str, freq="D")
    df_dias = pd.DataFrame({"fecha": rango_fechas})
    df_dias = df_dias.merge(df_clima, on="fecha", how="left")
    df_dias = df_dias.merge(df_ndvi, on="fecha", how="left")
    df_dias["riego_mm"] = 0.0  # cargar riegos reales acá si se registran en campo

    # 8. Correr el balance de forma incremental
    df_resultados, estado_nuevo = procesar_dias_nuevos(
        df_dias,
        estado,
        df_suelo,
        umbral_riego_pct=cfg["balance"]["umbral_riego_pct"],
        incremento_raiz_diario_cm=cfg["balance"]["incremento_raiz_diario_cm"],
        prof_raiz_max_cm=cfg["balance"]["prof_raiz_max_cm"],
        kc_a=cfg["balance"]["kc_a"],
        kc_b=cfg["balance"]["kc_b"],
    )

    # 9. Guardar CSV histórico y estado
    append_resultados_csv(cfg["rutas"]["salida_csv"], df_resultados)
    guardar_estado(cfg["rutas"]["estado_json"], estado_nuevo)

    # 10. Notificación de estado / alerta de riego
    if not df_resultados.empty:
        ultimo = df_resultados.iloc[-1]
        fecha_ultimo = (
            ultimo["fecha"].date() if hasattr(ultimo["fecha"], "date") else ultimo["fecha"]
        )
        log.info(
            "Última fecha procesada: %s | %%AU=%.1f | AU real=%.1f mm | NDVI=%.3f",
            fecha_ultimo,
            ultimo["pct_au"],
            ultimo["au_real_mm"],
            ultimo["ndvi"],
        )

        umbral = cfg["balance"]["umbral_riego_pct"]
        if ultimo["pct_au"] < umbral:
            log.warning(
                "⚠️  ALERTA DE RIEGO: %% Agua Útil (%.1f%%) por debajo del umbral (%s%%).",
                ultimo["pct_au"],
                umbral,
            )

        # --- Telegram ---
        cfg_tg = cfg.get("telegram", {})
        if cfg_tg.get("habilitado", False):
            tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if not tg_token or not tg_chat_id:
                log.warning(
                    "Telegram habilitado en config pero faltan TELEGRAM_BOT_TOKEN / "
                    "TELEGRAM_CHAT_ID. Se omite la notificación."
                )
            else:
                # %AU del día anterior al bloque nuevo, para detectar el cruce
                # de umbral (viene del estado previo, no del df de esta corrida).
                pct_au_previo = None
                if len(df_resultados) > 1:
                    pct_au_previo = float(df_resultados.iloc[-2]["pct_au"])
                elif estado.ultima_fecha_procesada:
                    # Corrida con un solo día nuevo: comparar contra el estado guardado
                    au_max_ref = float(ultimo["au_max_mm"])
                    if au_max_ref > 0:
                        pct_au_previo = (estado.au_real_mm / au_max_ref) * 100

                if debe_notificar(
                    float(ultimo["pct_au"]),
                    pct_au_previo,
                    umbral,
                    modo=cfg_tg.get("modo", "cruce"),
                ):
                    lluvia_7d = float(df_resultados.tail(7)["precipitacion_mm"].sum())
                    mensaje = armar_mensaje(
                        fecha=fecha_ultimo,
                        au_real_mm=float(ultimo["au_real_mm"]),
                        au_max_mm=float(ultimo["au_max_mm"]),
                        pct_au=float(ultimo["pct_au"]),
                        ndvi=float(ultimo["ndvi"]),
                        etc_mm=float(ultimo["etc_ajustada_mm"]),
                        precipitacion_7d_mm=lluvia_7d,
                        umbral_riego_pct=umbral,
                        nombre_lote=cfg_tg.get("nombre_lote", "Lote 20"),
                        eficiencia_aplicacion=cfg_tg.get("eficiencia_aplicacion", 0.85),
                        reposicion_objetivo_pct=cfg_tg.get("reposicion_objetivo_pct", 100.0),
                    )
                    enviar_telegram(tg_token, tg_chat_id, mensaje)
                else:
                    log.info("Sin condiciones para notificar (modo=%s).", cfg_tg.get("modo", "cruce"))

    log.info("Corrida finalizada OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
