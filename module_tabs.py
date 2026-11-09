"""
module_tabs.py — Tab & Window Switcher
Simulates keyboard shortcuts for switching browser tabs and OS windows
using pyautogui hotkeys. All actions are non-destructive navigation only.
"""

from __future__ import annotations

import logging
import platform
import random
import time
from typing import Callable

import pyautogui

logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08

# ── Platform detection ────────────────────────────────────────────────────────
IS_MAC: bool = platform.system() == "Darwin"
OS_NAME: str = platform.system()

# On Mac, window switching uses Cmd+Tab; on Windows it's Alt+Tab
WINDOW_SWITCH_MOD: str = "command" if IS_MAC else "alt"

# Browser tab hotkeys use Ctrl on Windows, also Ctrl on Mac (not Cmd)
# Ctrl+Tab, Ctrl+1–8, Ctrl+L all work identically on both platforms in browsers.

logger.debug("Platform: %s | Window switch modifier: %s", OS_NAME, WINDOW_SWITCH_MOD)

# Short pause after each hotkey to let the OS/app respond
POST_HOTKEY_DELAY_RANGE: tuple[float, float] = (0.4, 1.0)


# ── Internal helper ───────────────────────────────────────────────────────────

def _hotkey(*keys: str, label: str = "") -> None:
    """
    Press a hotkey combination and wait for the UI to respond.

    Args:
        *keys: Key names passed directly to pyautogui.hotkey().
        label: Human-readable description used in log output.
    """
    description = label or "+".join(keys)
    logger.debug("Hotkey → %s", description)
    pyautogui.hotkey(*keys)
    time.sleep(random.uniform(*POST_HOTKEY_DELAY_RANGE))


# ── Tab actions (identical on Windows & Mac) ──────────────────────────────────

def switch_tab_forward() -> None:
    """Move to the next browser tab (Ctrl+Tab — works on both platforms)."""
    _hotkey("ctrl", "tab", label="ctrl+tab (next tab)")


def switch_tab_backward() -> None:
    """Move to the previous browser tab (Ctrl+Shift+Tab — works on both platforms)."""
    _hotkey("ctrl", "shift", "tab", label="ctrl+shift+tab (prev tab)")


def switch_to_tab_number() -> None:
    """
    Jump to a browser tab by number (Ctrl+1 through Ctrl+8).
    Works on Chrome, Firefox, Edge on both Windows and Mac.
    """
    n = str(random.randint(1, 8))
    _hotkey("ctrl", n, label=f"ctrl+{n} (tab #{n})")


# ── Window actions (platform-aware) ───────────────────────────────────────────

def switch_window_forward() -> None:
    """
    Cycle forward through open OS windows.
    Windows: Alt+Tab  |  Mac: Cmd+Tab
    """
    _hotkey(WINDOW_SWITCH_MOD, "tab",
            label=f"{WINDOW_SWITCH_MOD}+tab (next window)")


def switch_window_backward() -> None:
    """
    Cycle backward through open OS windows.
    Windows: Alt+Shift+Tab  |  Mac: Cmd+Shift+Tab
    """
    _hotkey(WINDOW_SWITCH_MOD, "shift", "tab",
            label=f"{WINDOW_SWITCH_MOD}+shift+tab (prev window)")


# ── Address bar focus (identical on Windows & Mac) ────────────────────────────

def focus_address_bar() -> None:
    """
    Focus the browser address bar then dismiss with Escape.
    Ctrl+L works on Chrome/Firefox/Edge/Safari on both platforms.
    """
    _hotkey("ctrl", "l", label="ctrl+l (focus address bar)")
    time.sleep(0.2)
    pyautogui.press("escape")
    time.sleep(0.2)


# ── Action registry ───────────────────────────────────────────────────────────

TAB_ACTIONS: list[tuple[Callable[[], None], int]] = [
    (switch_tab_forward,     35),
    (switch_tab_backward,    25),
    (switch_to_tab_number,   20),
    (switch_window_forward,  15),
    (focus_address_bar,       5),
]

_ACTION_POOL: list[Callable[[], None]] = [
    action for action, weight in TAB_ACTIONS for _ in range(weight)
]


def run_random_tab_action() -> str:
    """
    Pick and execute a weighted-random tab or window action.

    Returns:
        Name of the action that was executed.
    """
    action = random.choice(_ACTION_POOL)
    action()
    return action.__name__
