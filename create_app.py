#!/usr/bin/env python3
"""
create_app.py — Packages UI Macro Tool as a double-clickable app.

macOS  → builds  "UI Macro Tool.app"  (drop onto Desktop or Applications)
Windows→ builds  "UI Macro Tool.bat"  (double-click to run)

What the resulting app does on first launch:
  1. Checks for Python 3.10+  (shows a dialog if missing, links to installer)
  2. Creates a private virtual-environment inside the bundle
  3. Installs all pip packages silently into that venv
  4. Opens the Settings window — no terminal ever appears

Subsequent launches skip steps 1–3 and open the UI immediately.

Usage:
    python create_app.py            # auto-detects platform
    python create_app.py --desktop  # also copies result to ~/Desktop
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.resolve()

# Source files to bundle inside the app
SOURCE_FILES = [
    "main.py",
    "module_input.py",
    "module_tabs.py",
    "config.py",
    "profiles.py",
    "settings_window.py",
    "ui_window.py",
    "requirements.txt",
]

# ── macOS .app bundle ─────────────────────────────────────────────────────────

MACOS_INFO_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>UI Macro Tool</string>
    <key>CFBundleDisplayName</key>
    <string>UI Macro Tool</string>
    <key>CFBundleIdentifier</key>
    <string>com.local.ui-macro-tool</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleExecutable</key>
    <string>run</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSUIElement</key>
    <false/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSAppleEventsUsageDescription</key>
    <string>UI Macro Tool uses Apple Events for setup dialogs.</string>
    <key>NSAccessibilityUsageDescription</key>
    <string>UI Macro Tool needs Accessibility access to simulate mouse and keyboard actions.</string>
</dict>
</plist>
"""

# Shell script that lives at Contents/MacOS/run inside the .app bundle.
# It auto-installs Python deps into a private venv on first launch.
MACOS_LAUNCHER = r"""#!/bin/bash
# UI Macro Tool — macOS launcher
# Located at: UI Macro Tool.app/Contents/MacOS/run

set -euo pipefail

APP_CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$APP_CONTENTS/Resources/src"
VENV="$APP_CONTENTS/Resources/venv"
REQ="$SRC/requirements.txt"
STAMP="$VENV/.installed"

# ── dialog helper ─────────────────────────────────────────────────────────────
dialog() {
    osascript -e "display dialog \"$1\" buttons {\"OK\"} default button 1 \
        with title \"UI Macro Tool\"" >/dev/null 2>&1 || true
}

open_url() {
    osascript -e "open location \"$1\"" >/dev/null 2>&1 || open "$1" || true
}

# ── 1. Expand PATH to cover all common Python install locations ───────────────
# .app bundles launch with a stripped PATH that misses python.org, Homebrew, etc.
export PATH="\
/Library/Frameworks/Python.framework/Versions/3.15/bin:\
/Library/Frameworks/Python.framework/Versions/3.14/bin:\
/Library/Frameworks/Python.framework/Versions/3.13/bin:\
/Library/Frameworks/Python.framework/Versions/3.12/bin:\
/Library/Frameworks/Python.framework/Versions/3.11/bin:\
/Library/Frameworks/Python.framework/Versions/3.10/bin:\
/usr/local/bin:\
/usr/bin:\
/opt/homebrew/bin:\
/opt/homebrew/opt/python@3.13/bin:\
/opt/homebrew/opt/python@3.12/bin:\
/opt/homebrew/opt/python@3.11/bin:\
/opt/homebrew/opt/python@3.10/bin:\
$PATH"

# ── 2. Find Python 3.10+ ──────────────────────────────────────────────────────
PYTHON=""
for candidate in \
    python3.15 python3.14 python3.13 python3.12 python3.11 python3.10 python3
do
    if command -v "$candidate" &>/dev/null; then
        OK=$("$candidate" -c \
            "import sys; print(1 if sys.version_info>=(3,10) else 0)" 2>/dev/null \
            || echo 0)
        if [ "$OK" = "1" ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    dialog "Python 3.10 or newer is required but was not found.\n\nClick OK to open the download page, then re-launch this app after installing."
    open_url "https://www.python.org/downloads/"
    exit 1
fi

# ── 3. Create venv on first launch ───────────────────────────────────────────
if [ ! -d "$VENV" ]; then
    osascript -e 'display notification "First launch — creating environment…" \
        with title "UI Macro Tool"' >/dev/null 2>&1 || true
    "$PYTHON" -m venv "$VENV"
fi

# ── 4. Install / update packages if stamp is missing ─────────────────────────
if [ ! -f "$STAMP" ]; then
    osascript -e 'display notification "Installing packages… please wait." \
        with title "UI Macro Tool"' >/dev/null 2>&1 || true
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$REQ"
    touch "$STAMP"
fi

# ── 5. Launch the app ─────────────────────────────────────────────────────────
cd "$SRC"
exec "$VENV/bin/python" main.py
"""

# ── Windows launcher ──────────────────────────────────────────────────────────

WINDOWS_LAUNCHER = r"""@echo off
setlocal EnableDelayedExpansion
title UI Macro Tool
cd /d "%~dp0"

REM ── 1. Find Python ───────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found on this machine.
    echo.
    echo Opening the Python download page...
    start https://www.python.org/downloads/
    echo After installing Python, run this file again.
    pause
    exit /b 1
)

REM ── 2. Check version (3.10+) ─────────────────────────────────────────────────
for /f %%v in ('python -c "import sys; print(1 if sys.version_info>=(3,10) else 0)"') do set PY_OK=%%v
if "!PY_OK!" neq "1" (
    echo Python 3.10 or newer is required.
    echo Please update Python at https://www.python.org/downloads/
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ── 3. Create venv if missing ────────────────────────────────────────────────
if not exist "venv\" (
    echo Setting up environment ^(first run only^)...
    python -m venv venv
)

REM ── 4. Install packages if stamp missing ────────────────────────────────────
if not exist "venv\.installed" (
    echo Installing packages...
    venv\Scripts\pip install --quiet -r requirements.txt
    type nul > "venv\.installed"
)

REM ── 5. Launch with no console window ────────────────────────────────────────
start "" venv\Scripts\pythonw.exe main.py
"""

# ── Icon generator ────────────────────────────────────────────────────────────

def _make_icon(out_dir: Path) -> Path | None:
    """
    Generate AppIcon.icns using Pillow + macOS iconutil.
    Returns path to .icns or None if Pillow / iconutil is unavailable.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        SIZE = 512
        img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # Dark blue rounded square background
        r = 100
        d.rounded_rectangle([0, 0, SIZE, SIZE], radius=r, fill=(15, 52, 96))

        # Green play triangle
        margin = 120
        pts = [
            (margin, margin),
            (margin, SIZE - margin),
            (SIZE - margin + 20, SIZE // 2),
        ]
        d.polygon(pts, fill=(68, 204, 102))

        # Save PNG
        png_path = out_dir / "icon_source.png"
        img.save(png_path)

        # Build iconset folder
        iconset = out_dir / "AppIcon.iconset"
        iconset.mkdir(exist_ok=True)
        for size in [16, 32, 64, 128, 256, 512]:
            resized = img.resize((size, size), Image.LANCZOS)
            resized.save(iconset / f"icon_{size}x{size}.png")
            if size <= 256:
                double = img.resize((size * 2, size * 2), Image.LANCZOS)
                double.save(iconset / f"icon_{size}x{size}@2x.png")

        # Convert to ICNS
        icns_path = out_dir / "AppIcon.icns"
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
            capture_output=True,
        )
        if result.returncode == 0 and icns_path.exists():
            shutil.rmtree(iconset)
            png_path.unlink(missing_ok=True)
            return icns_path
    except Exception:
        pass
    return None


# ── macOS builder ─────────────────────────────────────────────────────────────

def build_macos(copy_to_desktop: bool) -> Path:
    app_name  = "UI Macro Tool"
    dist      = HERE / "dist"
    app_path  = dist / f"{app_name}.app"
    contents  = app_path / "Contents"
    macos_dir = contents / "MacOS"
    res_dir   = contents / "Resources"
    src_dir   = res_dir / "src"

    print(f"Building  {app_path.name} …")

    # Clean previous build
    if app_path.exists():
        shutil.rmtree(app_path)

    # Create directory structure
    for d in (macos_dir, src_dir):
        d.mkdir(parents=True)

    # Info.plist
    (contents / "Info.plist").write_text(MACOS_INFO_PLIST)

    # Launcher script (Contents/MacOS/run)
    launcher = macos_dir / "run"
    launcher.write_text(MACOS_LAUNCHER)
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # Copy source files
    missing = []
    for name in SOURCE_FILES:
        src = HERE / name
        if src.exists():
            shutil.copy2(src, src_dir / name)
        else:
            missing.append(name)
    if missing:
        print(f"  Warning: source files not found — {missing}")

    # Copy config.json if present
    cfg = HERE / "config.json"
    if cfg.exists():
        shutil.copy2(cfg, src_dir / "config.json")

    # Generate icon
    icns = _make_icon(res_dir)
    if icns:
        print("  Icon: generated AppIcon.icns")
    else:
        print("  Icon: skipped (install Pillow for a custom icon: pip install Pillow)")

    print(f"  Built → {app_path}")

    if copy_to_desktop:
        desktop = Path.home() / "Desktop" / f"{app_name}.app"
        if desktop.exists():
            shutil.rmtree(desktop)
        shutil.copytree(app_path, desktop)
        print(f"  Copied → {desktop}")

    _print_macos_notes(app_path, copy_to_desktop)
    return app_path


def _print_macos_notes(app_path: Path, on_desktop: bool) -> None:
    loc = "~/Desktop/UI Macro Tool.app" if on_desktop else str(app_path)
    print()
    print("=" * 60)
    print("  macOS: Done!")
    print("=" * 60)
    print(f"  App location : {loc}")
    print()
    print("  FIRST-TIME SETUP")
    print("  ─────────────────────────────────────────────────────")
    print("  1. Double-click the app icon.")
    print("  2. If macOS blocks it: right-click → Open → Open.")
    print("  3. The app installs packages automatically on first run.")
    print("  4. Grant Accessibility permission when prompted:")
    print("     System Settings → Privacy & Security → Accessibility")
    print("     → toggle on  'UI Macro Tool'  (required for mouse/key control)")
    print()
    print("  SUBSEQUENT LAUNCHES")
    print("  ─────────────────────────────────────────────────────")
    print("  Just double-click the icon — the Settings window opens instantly.")
    print("=" * 60)


# ── Windows builder ───────────────────────────────────────────────────────────

def build_windows(copy_to_desktop: bool) -> Path:
    dist = HERE / "dist"
    dist.mkdir(exist_ok=True)
    bat  = dist / "UI Macro Tool.bat"

    print(f"Building  {bat.name} …")
    bat.write_text(WINDOWS_LAUNCHER)

    # Copy source files next to the .bat
    missing = []
    for name in SOURCE_FILES:
        src = HERE / name
        if src.exists():
            shutil.copy2(src, dist / name)
        else:
            missing.append(name)
    if missing:
        print(f"  Warning: source files not found — {missing}")

    cfg = HERE / "config.json"
    if cfg.exists():
        shutil.copy2(cfg, dist / "config.json")

    print(f"  Built → {bat}")

    if copy_to_desktop:
        desktop_bat = Path.home() / "Desktop" / "UI Macro Tool.bat"
        shutil.copy2(bat, desktop_bat)
        print(f"  Copied → {desktop_bat}")

    print()
    print("=" * 60)
    print("  Windows: Done!")
    print("=" * 60)
    print(f"  Launcher : {bat}")
    print()
    print("  Double-click 'UI Macro Tool.bat' to launch.")
    print("  On first run it installs packages then opens the UI.")
    print("  No terminal window will appear on subsequent runs.")
    print()
    print("  TIP: Right-click the .bat → Send to → Desktop (shortcut)")
    print("       to get a persistent desktop icon.")
    print("=" * 60)
    return bat


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Package UI Macro Tool as a double-clickable app.",
    )
    ap.add_argument("--desktop", action="store_true",
                    help="Also copy the result to ~/Desktop")
    args = ap.parse_args()

    system = platform.system()
    print("=" * 60)
    print("  UI Macro Tool — App Builder")
    print(f"  Platform: {system}")
    print("=" * 60)
    print()

    Path(HERE / "dist").mkdir(exist_ok=True)

    if system == "Darwin":
        build_macos(args.desktop)
    elif system == "Windows":
        build_windows(args.desktop)
    else:
        print(f"Platform '{system}' is not supported by this script.")
        print("On Linux, run directly:  python main.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
