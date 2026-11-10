"""
license_window.py — License activation window for UI Macro Tool.

Shows on startup when no valid cached license is found.
User enters their key → hits Activate → result shown inline.
Window closes automatically on success.

Design: dark theme, same palette as ui_window.py.
Uses tk.Label for buttons (macOS aqua theme overrides tk.Button colours).
"""
from __future__ import annotations

import threading
import tkinter as tk
from typing import Optional

from license_manager import LicenseManager, LicenseResult

# ── Palette (matches ui_window.py) ────────────────────────────────────────────

BG        = "#1a1a2e"
BG_CARD   = "#16213e"
BG_ENTRY  = "#0f3460"
BG_HEADER = "#0f3460"
FG_WHITE  = "#ffffff"
FG_LABEL  = "#aabbcc"
FG_DIM    = "#6c757d"
FG_ERROR  = "#ff5555"
FG_OK     = "#44cc66"
FG_WARN   = "#ffcc44"

BTN_ACTIVATE    = "#0f3460"
BTN_ACTIVATE_HV = "#1a4a80"
BTN_CLOSE       = "#2a2a3e"
BTN_CLOSE_HV    = "#3a3a4e"


class LicenseWindow:
    """
    Blocking modal window for license activation.

    Usage:
        result = LicenseWindow().run()
        if result:          # LicenseResult with success=True
            launch_app()
        else:
            sys.exit()      # user cancelled
    """

    def __init__(self) -> None:
        self._manager = LicenseManager()
        self._result: Optional[LicenseResult] = None
        self._root:   Optional[tk.Tk] = None

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build(self) -> None:
        root = tk.Tk()
        self._root = root
        root.title("UI Macro Tool — License Activation")
        root.configure(bg=BG)
        root.resizable(True, True)
        root.minsize(420, 340)

        # Centre on screen at a generous default size
        w, h = 520, 420
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        # Stay on screen even on small displays
        h = min(h, sh - 80)
        w = min(w, sw - 40)
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        # ── Header (fixed at top) ─────────────────────────────────────────────
        hdr = tk.Frame(root, bg=BG_HEADER, height=52)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="UI Macro Tool",
            bg=BG_HEADER, fg=FG_WHITE,
            font=("Helvetica", 16, "bold"),
        ).pack(side="left", padx=20)
        tk.Label(
            hdr, text="License Activation",
            bg=BG_HEADER, fg=FG_LABEL,
            font=("Helvetica", 11),
        ).pack(side="right", padx=20)

        # ── Buttons bar (pinned to bottom so they're always visible) ──────────
        btn_bar = tk.Frame(root, bg=BG, pady=12)
        btn_bar.pack(fill="x", side="bottom", padx=20)

        self._act_btn = self._make_btn(
            btn_bar, "  Activate  ",
            self._on_activate, BTN_ACTIVATE, BTN_ACTIVATE_HV,
            font=("Helvetica", 12, "bold"), fg=FG_WHITE,
        )
        self._act_btn.pack(side="left", padx=(0, 10))

        self._make_btn(
            btn_bar, "  Cancel  ",
            self._on_cancel, BTN_CLOSE, BTN_CLOSE_HV,
            font=("Helvetica", 12), fg=FG_DIM,
        ).pack(side="left")

        # Days-remaining label sits next to buttons
        self._days_lbl = tk.Label(
            btn_bar, text="",
            bg=BG, fg=FG_OK,
            font=("Helvetica", 10, "italic"),
        )
        self._days_lbl.pack(side="left", padx=16)

        # ── Scrollable content area ───────────────────────────────────────────
        canvas = tk.Canvas(root, bg=BG_CARD, highlightthickness=0)
        scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(8, 0))

        inner = tk.Frame(canvas, bg=BG_CARD)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_resize(event):
            canvas.itemconfig(inner_id, width=event.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_inner_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_resize)

        # Mouse-wheel scrolling (Windows + macOS)
        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>",   _on_mousewheel)
        canvas.bind_all("<Button-5>",   _on_mousewheel)

        # ── Content inside scroll area ────────────────────────────────────────
        pad = {"padx": 24, "pady": 0}

        tk.Label(
            inner,
            text="Enter your license key to activate this software.",
            bg=BG_CARD, fg=FG_LABEL,
            font=("Helvetica", 11),
            wraplength=440, justify="left",
        ).pack(anchor="w", pady=(22, 14), **pad)

        tk.Label(
            inner, text="License Key",
            bg=BG_CARD, fg=FG_LABEL,
            font=("Helvetica", 10),
        ).pack(anchor="w", **pad)

        self._key_var = tk.StringVar()
        entry = tk.Entry(
            inner,
            textvariable=self._key_var,
            bg=BG_ENTRY, fg=FG_WHITE, insertbackground=FG_WHITE,
            relief="flat", bd=0,
            font=("Courier", 12),
        )
        entry.pack(fill="x", ipady=8, pady=(4, 0), **pad)
        entry.bind("<Return>", lambda _: self._on_activate())
        entry.focus_set()

        tk.Label(
            inner,
            text="Paste the full key provided at purchase (starts with  key/…)",
            bg=BG_CARD, fg=FG_DIM, font=("Helvetica", 9),
        ).pack(anchor="w", pady=(4, 16), **pad)

        # Status message label
        self._msg_var = tk.StringVar(value="")
        self._msg_lbl = tk.Label(
            inner, textvariable=self._msg_var,
            bg=BG_CARD, fg=FG_WARN,
            font=("Helvetica", 10), wraplength=440, justify="left",
        )
        self._msg_lbl.pack(anchor="w", pady=(0, 10), **pad)

    # ── Button factory ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_btn(
        parent: tk.Widget, text: str, command,
        bg: str, hover_bg: str,
        font=("Helvetica", 12), fg: str = FG_WHITE,
    ) -> tk.Label:
        lbl = tk.Label(
            parent, text=text,
            bg=bg, fg=fg, font=font,
            padx=14, pady=7,
            cursor="hand2",
        )
        lbl.bind("<Button-1>", lambda _: command())
        lbl.bind("<Enter>",    lambda _: lbl.config(bg=hover_bg))
        lbl.bind("<Leave>",    lambda _: lbl.config(bg=bg))
        return lbl

    # ── Activation flow ────────────────────────────────────────────────────────

    def _on_activate(self) -> None:
        key = self._key_var.get().strip()
        if not key:
            self._show_msg("Please enter your license key.", FG_WARN)
            return

        self._show_msg("Validating key…", FG_LABEL)
        self._act_btn.config(state="disabled", cursor="")

        def _validate():
            result = self._manager.activate(key)
            self._root.after(0, lambda: self._handle_result(result))

        threading.Thread(target=_validate, daemon=True).start()

    def _handle_result(self, result: LicenseResult) -> None:
        self._act_btn.config(state="normal", cursor="hand2")

        if result.success:
            self._show_msg("", FG_OK)
            days_txt = (
                f"Activated — {result.days_remaining} day(s) remaining."
                if result.days_remaining is not None
                else "Key active."
            )
            self._days_lbl.config(text=days_txt, fg=FG_OK)
            self._result = result
            self._root.after(1400, self._root.destroy)
        else:
            self._show_msg(result.message, FG_ERROR)

    def _show_msg(self, text: str, color: str) -> None:
        self._msg_var.set(text)
        self._msg_lbl.config(fg=color)

    # ── Cancel ─────────────────────────────────────────────────────────────────

    def _on_cancel(self) -> None:
        self._result = None
        self._root.destroy()

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(self) -> Optional[LicenseResult]:
        """
        Open the activation window and block until the user activates or cancels.
        Returns a successful LicenseResult on activation, None if cancelled.
        """
        self._build()
        self._root.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._root.mainloop()
        return self._result
