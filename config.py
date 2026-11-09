"""
config.py — Persistent configuration management.
Saves/loads settings from config.json in the tool's directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_FILE = Path(__file__).parent / "config.json"


def load(path: Path = CONFIG_FILE) -> dict[str, Any]:
    """Load config from JSON. Returns empty dict if file missing or invalid."""
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save(cfg: dict[str, Any], path: Path = CONFIG_FILE) -> None:
    """Write config dict to JSON (pretty-printed)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def delete(path: Path = CONFIG_FILE) -> bool:
    """Delete the config file. Returns True if it existed."""
    if path.exists():
        path.unlink()
        return True
    return False
