"""
auth_cdse.py
------------
Obtiene (y cachea en memoria) el token OAuth2 (client_credentials) para
usar las APIs de Copernicus Data Space Ecosystem (Sentinel Hub Process /
Statistical API), a partir de un client_id + client_secret creados en:

    https://shapps.dataspace.copernicus.eu/dashboard/  ->  "User settings" ->
    "OAuth clients" -> "Create new OAuth client"

Las credenciales NUNCA deben quedar hardcodeadas en el código: se leen de
variables de entorno (o de config.yaml, que a su vez puede apuntar a un
archivo .env). Ver README.md para el detalle.
"""
from __future__ import annotations

import time
import logging

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)

_cache = {"token": None, "expira_en": 0}


def obtener_token(client_id: str, client_secret: str) -> str:
    """Devuelve un access_token válido, renovándolo si venció (con margen de 60s)."""
    ahora = time.time()
    if _cache["token"] and ahora < _cache["expira_en"] - 60:
        return _cache["token"]

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"No se pudo autenticar contra Copernicus Data Space Ecosystem "
            f"({resp.status_code}): {resp.text}"
        )
    data = resp.json()
    _cache["token"] = data["access_token"]
    _cache["expira_en"] = ahora + data.get("expires_in", 600)
    logger.info("Token CDSE obtenido, válido por %s s.", data.get("expires_in"))
    return _cache["token"]
