"""
module_input.py — Mouse, Scroll & Keypress Simulator
Provides randomised, non-disruptive input actions using pyautogui.
PyAutoGUI's failsafe is enabled — move the mouse to the top-left corner
of the screen at any time to abort execution immediately.
"""

from __future__ import annotations

import logging
import platform
import random
import time
from typing import Callable

import pyautogui

logger = logging.getLogger(__name__)

# ── Platform detection ────────────────────────────────────────────────────────
IS_MAC: bool = platform.system() == "Darwin"
IS_WINDOWS: bool = platform.system() == "Windows"
OS_NAME: str = platform.system()

# ── Safety configuration ──────────────────────────────────────────────────────
pyautogui.FAILSAFE = True       # Moving mouse to corner raises FailSafeException
pyautogui.PAUSE = 0.08          # Slight pause injected between every pyautogui call

# Screen dimensions (fetched once at import time)
SCREEN_W, SCREEN_H = pyautogui.size()

# Safe margin in pixels kept away from screen edges to avoid triggering failsafe
EDGE_MARGIN: int = 100

# Keys shared across all platforms.
# Rules for inclusion:
#   ✓ Navigation / view-only — does NOT activate, submit, delete, or type anything
#   ✗ space    — activates focused buttons/links, submits forms, plays media
#   ✗ enter    — submits forms, activates focused controls, confirms dialogs
#   ✗ return   — same as enter
#   ✗ tab      — moves focus between interactive elements (unpredictable)
#   ✗ delete   — deletes content / files
#   ✗ backspace — deletes text, navigates back in browsers
#   ✗ any letter/number — types visible characters into focused inputs
#   ✗ f-keys   — F1 help, F4 close, F5 refresh, F12 devtools, etc.
_COMMON_SAFE_KEYS: list[str] = [
    "shift",    # modifier only — pressing alone does nothing visible
    "escape",   # dismisses dialogs/menus/tooltips; never submits
    "home",     # cursor/scroll to start of line or page
    "end",      # cursor/scroll to end of line or page
    "pageup",   # scroll up one page
    "pagedown", # scroll down one page
]

# scrolllock and numlock do not exist on standard Mac keyboards
_WINDOWS_ONLY_KEYS: list[str] = ["scrolllock", "numlock"]

SAFE_KEYS: list[str] = (
    _COMMON_SAFE_KEYS if IS_MAC else _COMMON_SAFE_KEYS + _WINDOWS_ONLY_KEYS
)

logger.debug("Platform: %s | Safe keys loaded: %s", OS_NAME, SAFE_KEYS)

# Duration range (seconds) for animated mouse movements
MOUSE_DURATION_RANGE: tuple[float, float] = (0.3, 1.2)

# Scroll click range per action (positive = up, negative = down)
SCROLL_RANGE: tuple[int, int] = (-5, 5)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_x() -> int:
    """Return a random X coordinate safely away from screen edges."""
    return random.randint(EDGE_MARGIN, SCREEN_W - EDGE_MARGIN)


def _safe_y() -> int:
    """Return a random Y coordinate safely away from screen edges."""
    return random.randint(EDGE_MARGIN, SCREEN_H - EDGE_MARGIN)


# ── Public actions ────────────────────────────────────────────────────────────

def simulate_mouse_move() -> None:
    """
    Move the mouse to a random on-screen position with a smooth animation.
    Keeps the cursor away from corner failsafe zones.
    """
    x, y = _safe_x(), _safe_y()
    duration = round(random.uniform(*MOUSE_DURATION_RANGE), 2)
    logger.debug("Mouse move → (%d, %d) over %.2fs", x, y, duration)
    pyautogui.moveTo(x, y, duration=duration, tween=pyautogui.easeInOutQuad)


def simulate_scroll() -> None:
    """
    Scroll the page at the current cursor position by a random click amount.
    Positive clicks scroll up; negative scroll down.
    """
    clicks = random.randint(*SCROLL_RANGE)
    if clicks == 0:
        clicks = 1  # Ensure at least some scroll occurs
    logger.debug("Scroll %+d clicks", clicks)
    pyautogui.scroll(clicks)
    time.sleep(random.uniform(0.1, 0.4))


def simulate_keypress() -> None:
    """
    Press a randomly selected safe, non-disruptive key.
    None of these keys trigger destructive actions in standard applications.
    """
    key = random.choice(SAFE_KEYS)
    logger.debug("Keypress → %s", key)
    pyautogui.press(key)
    time.sleep(random.uniform(0.1, 0.3))


def simulate_mouse_and_scroll() -> None:
    """
    Compound action: move the mouse then immediately scroll at that position.
    """
    simulate_mouse_move()
    time.sleep(random.uniform(0.2, 0.5))
    simulate_scroll()


# ── Action registry ───────────────────────────────────────────────────────────
# Weights control relative frequency: mouse moves happen more often than keypresses.

INPUT_ACTIONS: list[tuple[Callable[[], None], int]] = [
    (simulate_mouse_move,       40),
    (simulate_scroll,           30),
    (simulate_keypress,         15),
    (simulate_mouse_and_scroll, 15),
]

_ACTION_POOL: list[Callable[[], None]] = [
    action for action, weight in INPUT_ACTIONS for _ in range(weight)
]


def run_random_input_action() -> str:
    """
    Pick and execute a weighted-random input action.

    Returns:
        Name of the action that was executed.
    """
    action = random.choice(_ACTION_POOL)
    action()
    return action.__name__
