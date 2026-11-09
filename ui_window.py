"""
ui_window.py — Status window for UI Macro Tool.
Runs on the main thread; the macro loop runs in a background thread.
No OS notifications or toasts are shown at any point.

Features:
  • Configuration panel (settings at a glance)
  • Live status panel (cycle, actions, last action, elapsed, errors)
  • Scrollable live log panel (mirrors terminal logs, colour-coded)
  • Pause / Resume button
  • Stop button
  • All colours render correctly on macOS (uses tk.Label for buttons,
    not tk.Button — macOS aqua theme overrides Button bg/fg colours)
"""
from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from typing import Any, Callable

# ── Colour palette ─────────────────────────────────────────────────────────────

BG        = "#1a1a2e"
BG_HEADER = "#0f3460"
BG_LOG    = "#0d0d1a"
FG_LABEL  = "#6c757d"
FG_VALUE  = "#e9ecef"
FG_WHITE  = "#ffffff"

STATUS_COLORS: dict[str, str] = {
    "starting":  "#aaaaaa",
    "running":   "#44cc66",
    "idle":      "#4499ff",
    "paused":    "#ffaa33",
    "complete":  "#aaaaaa",
    "stopped":   "#cc4444",
}

LOG_COLORS: dict[str, str] = {
    "DEBUG":    "#555577",
    "INFO":     "#aabbcc",
    "WARNING":  "#ffcc44",
    "ERROR":    "#ff5555",
    "CRITICAL": "#ff2222",
}


# ── GUI log handler ────────────────────────────────────────────────────────────

class GuiLogHandler(logging.Handler):
    """
    Logging handler that appends records to the window's log panel.
    Thread-safe: schedules widget updates via root.after().
    """

    def __init__(self, append_fn: Callable[[str, str], None]) -> None:
        super().__init__()
        self._append = append_fn
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname
            self._append(msg, level)
        except Exception:
            self.handleError(record)


# ── Status window ──────────────────────────────────────────────────────────────

class MacroStatusWindow:
    """
    Lightweight tkinter window showing configuration, live stats, and logs.
    Thread-safe: macro thread calls update(); UI thread calls run().
    """

    def __init__(
        self,
        config: dict[str, Any],
        pause_event: threading.Event,
        stop_event: threading.Event,
    ) -> None:
        self._pause_event = pause_event
        self._stop_event  = stop_event
        self._max_cycles  = config.get("cycles")       # None = infinite
        self._start_time  = time.time()
        self._lock        = threading.Lock()

        # Live data written by the macro thread, read by _tick() on the UI thread
        self._status      = "Starting"
        self._cycle       = 0
        self._actions     = 0
        self._errors      = 0
        self._last_action = "—"

        self._root = tk.Tk()
        self._root.title("UI Macro Tool")
        self._root.resizable(False, False)
        self._root.configure(bg=BG)
        self._root.geometry("+120+80")

        self._build_ui(config)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, config: dict[str, Any]) -> None:
        P = {"padx": 14, "pady": 3}

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self._root, bg=BG_HEADER, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="UI Macro Tool",
                 font=("Helvetica", 14, "bold"), fg=FG_WHITE, bg=BG_HEADER).pack()
        tk.Label(hdr, text="Automation running in the background",
                 font=("Helvetica", 9), fg="#8899aa", bg=BG_HEADER).pack()

        # ── Two-column top section ────────────────────────────────────────────
        top = tk.Frame(self._root, bg=BG)
        top.pack(fill="x", padx=14, pady=(10, 4))

        # Config card (left)
        cfg_frame = tk.LabelFrame(top, text=" Configuration ",
                                  fg=FG_LABEL, bg=BG, font=("Helvetica", 9),
                                  relief="groove", bd=1)
        cfg_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

        cfg_rows = [
            ("Delay range",     f"{config.get('min_delay', 5)}m – {config.get('max_delay', 10)}m"),
            ("Actions / cycle", str(config.get("actions_per_cycle", 5))),
            ("Cycles",          str(config.get("cycles") or "∞  (infinite)")),
            ("Input weight",    str(config.get("input_weight", 60))),
            ("Tab weight",      str(config.get("tab_weight", 40))),
            ("Dry run",         "YES" if config.get("dry_run") else "No"),
        ]
        for label, val in cfg_rows:
            row = tk.Frame(cfg_frame, bg=BG)
            row.pack(fill="x", **P)
            tk.Label(row, text=label, width=14, anchor="w",
                     fg=FG_LABEL, bg=BG, font=("Helvetica", 10)).pack(side="left")
            color = "#ffaa33" if (label == "Dry run" and val == "YES") else FG_VALUE
            tk.Label(row, text=val, anchor="w",
                     fg=color, bg=BG, font=("Helvetica", 10, "bold")).pack(side="left")

        # Status card (right)
        stat_frame = tk.LabelFrame(top, text=" Live Status ",
                                   fg=FG_LABEL, bg=BG, font=("Helvetica", 9),
                                   relief="groove", bd=1)
        stat_frame.pack(side="left", fill="both", expand=True, padx=(6, 0))

        # Status row (coloured dot)
        sr = tk.Frame(stat_frame, bg=BG)
        sr.pack(fill="x", **P)
        tk.Label(sr, text="Status", width=12, anchor="w",
                 fg=FG_LABEL, bg=BG, font=("Helvetica", 10)).pack(side="left")
        self._dot = tk.Label(sr, text="●", fg="#aaaaaa", bg=BG,
                             font=("Helvetica", 10))
        self._dot.pack(side="left")
        self._status_lbl = tk.Label(sr, text="Starting", anchor="w",
                                    fg="#aaaaaa", bg=BG,
                                    font=("Helvetica", 10, "bold"))
        self._status_lbl.pack(side="left", padx=(4, 0))

        self._vars: dict[str, tk.StringVar] = {}
        for key, label in [
            ("cycle",   "Cycle"),
            ("actions", "Actions"),
            ("last",    "Last action"),
            ("elapsed", "Elapsed"),
            ("errors",  "Errors"),
        ]:
            v = tk.StringVar(value="—")
            self._vars[key] = v
            row = tk.Frame(stat_frame, bg=BG)
            row.pack(fill="x", **P)
            tk.Label(row, text=label, width=12, anchor="w",
                     fg=FG_LABEL, bg=BG, font=("Helvetica", 10)).pack(side="left")
            tk.Label(row, textvariable=v, anchor="w",
                     fg=FG_VALUE, bg=BG, font=("Helvetica", 10, "bold")).pack(side="left")

        # ── Log panel ─────────────────────────────────────────────────────────
        log_frame = tk.LabelFrame(self._root, text=" Live Logs ",
                                  fg=FG_LABEL, bg=BG, font=("Helvetica", 9),
                                  relief="groove", bd=1)
        log_frame.pack(fill="x", padx=14, pady=(4, 2))

        scrollbar = tk.Scrollbar(log_frame, bg=BG, troughcolor=BG)
        scrollbar.pack(side="right", fill="y")

        self._log_text = tk.Text(
            log_frame,
            height=9,
            bg=BG_LOG,
            fg="#aabbcc",
            font=("Courier", 9),
            state="disabled",
            wrap="none",
            yscrollcommand=scrollbar.set,
            bd=0,
            padx=6,
            pady=4,
            selectbackground="#2a2a4a",
        )
        self._log_text.pack(fill="x")
        scrollbar.config(command=self._log_text.yview)

        # Colour tags for log levels
        for level, color in LOG_COLORS.items():
            self._log_text.tag_config(level, foreground=color)

        # ── Buttons ───────────────────────────────────────────────────────────
        # tk.Label used instead of tk.Button — macOS aqua theme overrides
        # Button bg/fg colours; Labels render correctly on all platforms.
        btn_frame = tk.Frame(self._root, bg=BG, pady=12)
        btn_frame.pack()

        self._pause_btn = self._make_label_btn(
            btn_frame, text="Pause", command=self._toggle_pause,
            bg="#1a472a", hover_bg="#2a6e3a",
        )
        self._pause_btn.pack(side="left", padx=8)

        self._make_label_btn(
            btn_frame, text="Stop", command=self._on_stop,
            bg="#5a1a1a", hover_bg="#7a2d2d",
        ).pack(side="left", padx=8)

        # Failsafe hint
        tk.Label(self._root,
                 text="Move mouse to top-left corner to abort (failsafe)",
                 fg="#333355", bg=BG, font=("Helvetica", 8)).pack(pady=(0, 8))

    # ── Label-button factory ──────────────────────────────────────────────────

    @staticmethod
    def _make_label_btn(
        parent: tk.Frame,
        text: str,
        command: Callable[[], None],
        bg: str,
        hover_bg: str,
    ) -> tk.Label:
        """
        Return a tk.Label styled and wired as a clickable button.
        Labels respect bg/fg on macOS; tk.Button does not (aqua theme).
        """
        lbl = tk.Label(
            parent, text=text, bg=bg, fg=FG_WHITE,
            font=("Helvetica", 10, "bold"),
            cursor="hand2", padx=20, pady=7,
        )
        lbl.bind("<Button-1>", lambda _e: command())
        lbl.bind("<Enter>",    lambda _e: lbl.config(bg=hover_bg))
        lbl.bind("<Leave>",    lambda _e: lbl.config(bg=bg))
        return lbl

    # ── Button handlers ───────────────────────────────────────────────────────

    def _toggle_pause(self) -> None:
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._pause_btn.config(text="Pause", bg="#1a472a")
            self._pause_btn.unbind("<Enter>")
            self._pause_btn.unbind("<Leave>")
            self._pause_btn.bind("<Enter>", lambda _e: self._pause_btn.config(bg="#2a6e3a"))
            self._pause_btn.bind("<Leave>", lambda _e: self._pause_btn.config(bg="#1a472a"))
        else:
            self._pause_event.set()
            self._pause_btn.config(text="Resume", bg="#5a4a00")
            self._pause_btn.unbind("<Enter>")
            self._pause_btn.unbind("<Leave>")
            self._pause_btn.bind("<Enter>", lambda _e: self._pause_btn.config(bg="#7a6a00"))
            self._pause_btn.bind("<Leave>", lambda _e: self._pause_btn.config(bg="#5a4a00"))

    def _on_stop(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()
        self._root.after(1200, self._close_root)

    def _on_close(self) -> None:
        self._on_stop()

    def _close_root(self) -> None:
        try:
            self._root.destroy()
        except Exception:
            pass

    # ── Log panel append (thread-safe) ────────────────────────────────────────

    def append_log(self, message: str, level: str = "INFO") -> None:
        """Append a log line to the log panel. Safe to call from any thread."""
        def _do() -> None:
            self._log_text.config(state="normal")
            self._log_text.insert("end", message + "\n", level)
            self._log_text.config(state="disabled")
            self._log_text.see("end")           # auto-scroll to bottom

        try:
            self._root.after(0, _do)
        except Exception:
            pass

    def make_log_handler(self) -> GuiLogHandler:
        """Return a logging.Handler that writes records to this window's log panel."""
        return GuiLogHandler(self.append_log)

    # ── Thread-safe status update (called from macro thread) ──────────────────

    def update(
        self,
        status: str,
        cycle: int,
        actions: int,
        errors: int,
        last_action: str,
    ) -> None:
        """Store new values; _tick() pushes them to widgets on the UI thread."""
        with self._lock:
            self._status      = status
            self._cycle       = cycle
            self._actions     = actions
            self._errors      = errors
            self._last_action = last_action

    # ── Periodic refresh (UI thread only, via after) ──────────────────────────

    def _tick(self) -> None:
        with self._lock:
            status  = self._status
            cycle   = self._cycle
            actions = self._actions
            errors  = self._errors
            last    = self._last_action

        color = STATUS_COLORS.get(status.lower(), "#aaaaaa")
        self._dot.config(fg=color)
        self._status_lbl.config(text=status, fg=color)

        max_c = str(self._max_cycles) if self._max_cycles else "∞"
        self._vars["cycle"].set(f"{cycle} / {max_c}")
        self._vars["actions"].set(str(actions))
        self._vars["last"].set(last)
        self._vars["errors"].set("0" if errors == 0 else f"⚠  {errors}")

        s = int(time.time() - self._start_time)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        self._vars["elapsed"].set(
            f"{h}h {m:02d}m {sec:02d}s" if h else f"{m}m {sec:02d}s"
        )

        if not self._stop_event.is_set():
            self._root.after(500, self._tick)

    # ── Entry point (blocks main thread) ─────────────────────────────────────

    def run(self) -> None:
        """Start the refresh loop and enter tkinter mainloop (blocks)."""
        self._root.after(500, self._tick)
        self._root.mainloop()

    def close(self) -> None:
        """Safely destroy the window from any thread."""
        try:
            self._root.after(0, self._close_root)
        except Exception:
            pass
