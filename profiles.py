"""
profiles.py — Named configuration presets.
Each profile is a ready-made set of timing and weight values.
"""

from __future__ import annotations

from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "light": {
        "description": "Gentle activity — few actions, long pauses",
        "input_weight": 70,
        "tab_weight": 30,
        "actions_per_cycle": 3,
        "min_delay": 8,
        "max_delay": 15,
    },
    "heavy": {
        "description": "High activity — many actions, short pauses",
        "input_weight": 60,
        "tab_weight": 40,
        "actions_per_cycle": 8,
        "min_delay": 3,
        "max_delay": 7,
    },
    "tabs-only": {
        "description": "Only tab/window switching, no mouse or keyboard",
        "input_weight": 0,
        "tab_weight": 1,
        "actions_per_cycle": 5,
        "min_delay": 5,
        "max_delay": 10,
    },
    "input-only": {
        "description": "Only mouse/scroll/keypress, no tab switching",
        "input_weight": 1,
        "tab_weight": 0,
        "actions_per_cycle": 5,
        "min_delay": 5,
        "max_delay": 10,
    },
    "stealth": {
        "description": "Minimal footprint — very few actions, long gaps",
        "input_weight": 60,
        "tab_weight": 40,
        "actions_per_cycle": 2,
        "min_delay": 15,
        "max_delay": 30,
    },
}


def get(name: str) -> dict[str, Any] | None:
    """Return profile values (without the description key), or None if not found."""
    p = PROFILES.get(name)
    if p is None:
        return None
    return {k: v for k, v in p.items() if k != "description"}


def list_profiles() -> list[str]:
    return list(PROFILES.keys())
