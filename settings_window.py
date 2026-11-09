"""
settings_window.py — Configuration form shown before the macro starts.
User sets everything here: duration, timing, which actions, dry run, etc.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, field
from typing import Optional

import config as cfg_module
import profiles as profiles_module

# ── Colour palette (matches ui_window.py) ────────────────────────────────────

BG        = "#1a1a2e"
BG_HDR    = "#0f3460"
BG_CARD   = "#16213e"
FG        = "#e9ecef"
FG_DIM    = "#6c757d"
FG_WHITE  = "#ffffff"
FG_WARN   = "#ffaa33"
ACCENT    = "#4499ff"
GREEN     = "#44cc66"


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass
class MacroConfig:
    """All settings collected from the settings form."""

    # Duration
    run_mode: str = "indefinite"      # "indefinite" | "duration" | "cycles"
    max_hours: int = 0
    max_min_time: int = 0
    cycles: Optional[int] = None

    # Timing
    min_delay: int = 5
    max_delay: int = 10
    actions_per_cycle: int = 5

    # Action weights (input module vs tab module)
    input_weight: int = 60
    tab_weight: int = 40

    # Individual action enable/disable
    enabled_actions: set[str] = field(default_factory=lambda: {
        "simulate_mouse_move",
        "simulate_scroll",
        "simulate_keypress",
        "simulate_mouse_and_scroll",
        "switch_tab_forward",
        "switch_tab_backward",
        "switch_to_tab_number",
        "switch_window_forward",
        "focus_address_bar",
    })

    # Options
    dry_run: bool = False

    def max_duration_seconds(self) -> Optional[int]:
        """Return total run limit in seconds, or None if unlimited."""
        if self.run_mode == "duration":
            total = self.max_hours * 3600 + self.max_min_time * 60
            return total if total > 0 else None
        return None


# ── Settings window ───────────────────────────────────────────────────────────

class SettingsWindow:
    """
    Modal configuration form.
    Call run() — it blocks until the user clicks Start or closes the window.
    Returns MacroConfig on Start, None if window is closed without starting.
    """

    def __init__(self, initial: Optional[MacroConfig] = None) -> None:
        self._result: Optional[MacroConfig] = None
        cfg = initial or MacroConfig()

        self._root = tk.Tk()
        self._root.title("UI Macro Tool — Settings")
        self._root.resizable(False, False)
        self._root.configure(bg=BG)
        self._root.geometry("+100+60")

        # ── Form variables ────────────────────────────────────────────────────
        self._run_mode        = tk.StringVar(value=cfg.run_mode)
        self._max_hours       = tk.IntVar(value=cfg.max_hours)
        self._max_min_time    = tk.IntVar(value=cfg.max_min_time)
        self._cycles          = tk.IntVar(value=cfg.cycles or 10)
        self._min_delay       = tk.IntVar(value=cfg.min_delay)
        self._max_delay       = tk.IntVar(value=cfg.max_delay)
        self._apc             = tk.IntVar(value=cfg.actions_per_cycle)
        self._input_weight    = tk.IntVar(value=cfg.input_weight)
        self._dry_run         = tk.BooleanVar(value=cfg.dry_run)

        self._action_vars: dict[str, tk.BooleanVar] = {
            name: tk.BooleanVar(value=(name in cfg.enabled_actions))
            for name in [
                "simulate_mouse_move",
                "simulate_scroll",
                "simulate_keypress",
                "simulate_mouse_and_scroll",
                "switch_tab_forward",
                "switch_tab_backward",
                "switch_to_tab_number",
                "switch_window_forward",
                "focus_address_bar",
            ]
        }

        self._build_ui()
        self._root.protocol("WM_DELETE_WINDOW", lambda: self._root.destroy())

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _section(parent: tk.Widget, title: str) -> tk.LabelFrame:
        return tk.LabelFrame(
            parent, text=f"  {title}  ",
            fg=FG_DIM, bg=BG, font=("Helvetica", 9),
            relief="groove", bd=1,
        )

    @staticmethod
    def _label(parent: tk.Widget, text: str, fg: str = FG, **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=BG, fg=fg, font=("Helvetica", 10), **kw)

    @staticmethod
    def _spinbox(parent: tk.Widget, var: tk.IntVar, lo: int, hi: int, width: int = 5) -> tk.Spinbox:
        return tk.Spinbox(
            parent, from_=lo, to=hi, textvariable=var, width=width,
            bg=BG_CARD, fg=FG, insertbackground=FG, relief="flat",
            font=("Helvetica", 10), buttonbackground=BG_CARD,
        )

    @staticmethod
    def _make_label_btn(
        parent: tk.Widget,
        text: str,
        command,
        bg: str,
        hover_bg: str,
        width: int = 14,
    ) -> tk.Label:
        lbl = tk.Label(
            parent, text=text, bg=bg, fg=FG_WHITE,
            font=("Helvetica", 10, "bold"),
            cursor="hand2", padx=16, pady=8, width=width,
        )
        lbl.bind("<Button-1>", lambda _e: command())
        lbl.bind("<Enter>",    lambda _e: lbl.config(bg=hover_bg))
        lbl.bind("<Leave>",    lambda _e: lbl.config(bg=bg))
        return lbl

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self._root, bg=BG_HDR, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="UI Macro Tool",
                 font=("Helvetica", 14, "bold"), fg=FG_WHITE, bg=BG_HDR).pack()
        tk.Label(hdr, text="Configure your automation session",
                 font=("Helvetica", 9), fg="#8899aa", bg=BG_HDR).pack()

        # ── Scrollable body ───────────────────────────────────────────────────
        body = tk.Frame(self._root, bg=BG)
        body.pack(fill="both", padx=16, pady=10)

        P = {"fill": "x", "pady": 6}

        # ── 1. Duration ───────────────────────────────────────────────────────
        dur = self._section(body, "Duration")
        dur.pack(**P)

        # Indefinite
        self._rb(dur, "indefinite", "Run indefinitely").grid(row=0, column=0, sticky="w", padx=10, pady=4, columnspan=4)

        # For X hours Y minutes
        dur_row = tk.Frame(dur, bg=BG)
        dur_row.grid(row=1, column=0, sticky="w", padx=10, pady=4, columnspan=4)
        tk.Radiobutton(dur_row, text="Run for", variable=self._run_mode, value="duration",
                       bg=BG, fg=FG, selectcolor=BG_CARD, activebackground=BG,
                       font=("Helvetica", 10)).pack(side="left")
        self._sb_hours = self._spinbox(dur_row, self._max_hours, 0, 24, 3)
        self._sb_hours.pack(side="left", padx=4)
        self._label(dur_row, "hrs").pack(side="left")
        self._sb_min_time = self._spinbox(dur_row, self._max_min_time, 0, 59, 3)
        self._sb_min_time.pack(side="left", padx=4)
        self._label(dur_row, "min").pack(side="left")

        # For N cycles
        cyc_row = tk.Frame(dur, bg=BG)
        cyc_row.grid(row=2, column=0, sticky="w", padx=10, pady=4, columnspan=4)
        tk.Radiobutton(cyc_row, text="Run for", variable=self._run_mode, value="cycles",
                       bg=BG, fg=FG, selectcolor=BG_CARD, activebackground=BG,
                       font=("Helvetica", 10)).pack(side="left")
        self._sb_cycles = self._spinbox(cyc_row, self._cycles, 1, 9999, 5)
        self._sb_cycles.pack(side="left", padx=4)
        self._label(cyc_row, "cycles").pack(side="left")

        # ── 2. Timing ─────────────────────────────────────────────────────────
        tim = self._section(body, "Timing")
        tim.pack(**P)

        row1 = tk.Frame(tim, bg=BG)
        row1.pack(fill="x", padx=10, pady=4)
        self._label(row1, "Delay between cycles:").pack(side="left")
        self._spinbox(row1, self._min_delay, 0, 120, 4).pack(side="left", padx=6)
        self._label(row1, "–").pack(side="left")
        self._spinbox(row1, self._max_delay, 0, 120, 4).pack(side="left", padx=6)
        self._label(row1, "minutes  (random pick in this range)", fg=FG_DIM).pack(side="left")

        row2 = tk.Frame(tim, bg=BG)
        row2.pack(fill="x", padx=10, pady=4)
        self._label(row2, "Actions per cycle:").pack(side="left")
        self._spinbox(row2, self._apc, 1, 50, 4).pack(side="left", padx=6)
        self._label(row2, "actions  (how many to run before idling)", fg=FG_DIM).pack(side="left")

        # ── 3. Mouse & Keyboard actions ───────────────────────────────────────
        inp = self._section(body, "Mouse & Keyboard Actions")
        inp.pack(**P)

        self._action_check(inp, "simulate_mouse_move",       "Mouse move          (smooth random movement)")
        self._action_check(inp, "simulate_scroll",           "Scroll              (random up/down)")
        self._action_check(inp, "simulate_keypress",         "Safe keypress       (Shift / Escape / Home / End / PgUp / PgDn)")
        self._action_check(inp, "simulate_mouse_and_scroll", "Mouse + Scroll      (move then scroll)")

        # ── 4. Tab & Window actions ───────────────────────────────────────────
        tab = self._section(body, "Tab & Window Actions")
        tab.pack(**P)

        self._action_check(tab, "switch_tab_forward",    "Next tab            (Ctrl+Tab)")
        self._action_check(tab, "switch_tab_backward",   "Previous tab        (Ctrl+Shift+Tab)")
        self._action_check(tab, "switch_to_tab_number",  "Jump to tab 1–8     (Ctrl+1 … Ctrl+8)")
        self._action_check(tab, "switch_window_forward", "Switch window       (Cmd+Tab / Alt+Tab)")
        self._action_check(tab, "focus_address_bar",     "Address bar focus   (Ctrl+L then Escape)")

        # ── 5. Input vs Tab balance ───────────────────────────────────────────
        bal = self._section(body, "Mouse/Keyboard vs Tab balance")
        bal.pack(**P)

        bal_inner = tk.Frame(bal, bg=BG)
        bal_inner.pack(fill="x", padx=10, pady=6)

        self._label(bal_inner, "Mouse/Keyboard").pack(side="left")

        self._slider = tk.Scale(
            bal_inner, from_=0, to=100, orient="horizontal",
            variable=self._input_weight, length=220,
            bg=BG, fg=FG, troughcolor=BG_CARD, highlightthickness=0,
            sliderrelief="flat", command=self._on_slider,
        )
        self._slider.pack(side="left", padx=8)

        self._balance_lbl = tk.Label(
            bal_inner, text="60% input / 40% tabs",
            bg=BG, fg=ACCENT, font=("Helvetica", 10, "bold"),
        )
        self._balance_lbl.pack(side="left")

        self._on_slider(self._input_weight.get())   # init label

        # ── 6. Options ────────────────────────────────────────────────────────
        opt = self._section(body, "Options")
        opt.pack(**P)

        opt_row = tk.Frame(opt, bg=BG)
        opt_row.pack(fill="x", padx=10, pady=6)

        tk.Checkbutton(
            opt_row, text="Dry run  (simulate — no real mouse/keyboard actions)",
            variable=self._dry_run,
            bg=BG, fg=FG_WARN, selectcolor=BG_CARD, activebackground=BG,
            font=("Helvetica", 10),
        ).pack(side="left")

        # ── 7. Quick-load profile ─────────────────────────────────────────────
        prof = self._section(body, "Quick-load profile")
        prof.pack(**P)

        prof_row = tk.Frame(prof, bg=BG)
        prof_row.pack(fill="x", padx=10, pady=6)

        self._label(prof_row, "Profile:").pack(side="left")
        self._profile_var = tk.StringVar(value="— select —")
        choices = ["— select —"] + profiles_module.list_profiles()
        om = tk.OptionMenu(prof_row, self._profile_var, *choices, command=self._load_profile)
        om.config(bg=BG_CARD, fg=FG, activebackground=BG_HDR, activeforeground=FG_WHITE,
                  relief="flat", font=("Helvetica", 10), highlightthickness=0)
        om["menu"].config(bg=BG_CARD, fg=FG, activebackground=BG_HDR, activeforeground=FG_WHITE)
        om.pack(side="left", padx=8)

        self._label(prof_row, "Loads preset timing & weight values.",
                    fg=FG_DIM).pack(side="left")

        # ── Bottom bar ────────────────────────────────────────────────────────
        bar = tk.Frame(self._root, bg="#0d0d1a", pady=12)
        bar.pack(fill="x")

        btn_inner = tk.Frame(bar, bg="#0d0d1a")
        btn_inner.pack()

        self._make_label_btn(
            btn_inner, "Save as Default", self._save_default,
            bg="#1a3a5a", hover_bg="#2a5a8a", width=14,
        ).pack(side="left", padx=8)

        self._make_label_btn(
            btn_inner, "▶  Start", self._on_start,
            bg="#1a4a1a", hover_bg="#2a6e2a", width=14,
        ).pack(side="left", padx=8)

    def _rb(self, parent: tk.Widget, value: str, text: str) -> tk.Radiobutton:
        return tk.Radiobutton(
            parent, text=text, variable=self._run_mode, value=value,
            bg=BG, fg=FG, selectcolor=BG_CARD, activebackground=BG,
            font=("Helvetica", 10),
        )

    def _action_check(self, parent: tk.Widget, key: str, label: str) -> None:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=10, pady=2)
        tk.Checkbutton(
            row, text=label, variable=self._action_vars[key],
            bg=BG, fg=FG, selectcolor=BG_CARD, activebackground=BG,
            font=("Courier", 10),
        ).pack(side="left")

    # ── Live label callbacks ──────────────────────────────────────────────────

    def _on_slider(self, val) -> None:
        iw = int(float(val))
        tw = 100 - iw
        self._balance_lbl.config(text=f"{iw}% input / {tw}% tabs")

    # ── Profile loader ────────────────────────────────────────────────────────

    def _load_profile(self, name: str) -> None:
        if name == "— select —":
            return
        data = profiles_module.get(name)
        if not data:
            return
        self._min_delay.set(data.get("min_delay", 5))
        self._max_delay.set(data.get("max_delay", 10))
        self._apc.set(data.get("actions_per_cycle", 5))
        self._input_weight.set(data.get("input_weight", 60))
        self._on_slider(data.get("input_weight", 60))

    # ── Collect form values ───────────────────────────────────────────────────

    def _collect(self) -> Optional[MacroConfig]:
        iw = self._input_weight.get()
        tw = 100 - iw

        if iw == 0 and tw == 0:
            self._show_error("Input weight and tab weight cannot both be 0.")
            return None

        enabled = {k for k, v in self._action_vars.items() if v.get()}
        if not enabled:
            self._show_error("At least one action must be enabled.")
            return None

        min_d = self._min_delay.get()
        max_d = self._max_delay.get()
        if min_d > max_d:
            self._show_error("Min delay must be ≤ max delay.")
            return None

        return MacroConfig(
            run_mode          = self._run_mode.get(),
            max_hours         = self._max_hours.get(),
            max_min_time      = self._max_min_time.get(),
            cycles            = self._cycles.get() if self._run_mode.get() == "cycles" else None,
            min_delay         = min_d,
            max_delay         = max_d,
            actions_per_cycle = self._apc.get(),
            input_weight      = iw,
            tab_weight        = tw,
            enabled_actions   = enabled,
            dry_run           = self._dry_run.get(),
        )

    def _show_error(self, msg: str) -> None:
        win = tk.Toplevel(self._root)
        win.title("Error")
        win.configure(bg=BG)
        win.resizable(False, False)
        tk.Label(win, text=msg, bg=BG, fg="#ff5555",
                 font=("Helvetica", 10), padx=20, pady=12).pack()
        self._make_label_btn(win, "OK", win.destroy, "#5a1a1a", "#7a2d2d", width=8).pack(pady=(0, 12))

    # ── Button handlers ───────────────────────────────────────────────────────

    def _save_default(self) -> None:
        cfg = self._collect()
        if cfg is None:
            return
        to_save = {
            "min_delay":         cfg.min_delay,
            "max_delay":         cfg.max_delay,
            "actions_per_cycle": cfg.actions_per_cycle,
            "input_weight":      cfg.input_weight,
            "tab_weight":        cfg.tab_weight,
        }
        if cfg.run_mode == "cycles" and cfg.cycles:
            to_save["cycles"] = cfg.cycles
        cfg_module.save(to_save)

        win = tk.Toplevel(self._root)
        win.title("Saved")
        win.configure(bg=BG)
        win.resizable(False, False)
        tk.Label(win, text="✓  Settings saved to config.json", bg=BG, fg=GREEN,
                 font=("Helvetica", 10), padx=20, pady=12).pack()
        self._make_label_btn(win, "OK", win.destroy, "#1a472a", "#2a6e3a", width=8).pack(pady=(0, 12))

    def _on_start(self) -> None:
        cfg = self._collect()
        if cfg is None:
            return
        self._result = cfg
        self._root.destroy()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> Optional[MacroConfig]:
        """Block until Start or close. Returns MacroConfig or None."""
        self._root.mainloop()
        return self._result
