"""config.py - carga simple de config.yaml"""
from __future__ import annotations

from pathlib import Path

import yaml


def cargar_config(path: str | Path = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
