"""
main.py — Macro Automation Orchestrator

Default flow (GUI mode):
  1. Settings window opens — user configures everything via form
  2. Click Start → status window opens, macro begins
  3. Click Stop (or move mouse to corner) → clean exit with summary

Headless mode (--no-gui): uses CLI flags only, skips both windows.

No OS notifications or toasts at any point.

Usage:
    python main.py                 # GUI: settings → status window
    python main.py --no-gui        # terminal only, all flags required
    python main.py --no-gui --profile heavy --cycles 10
    python main.py --list-profiles
    python main.py --no-gui --dry-run --cycles 3 --min-delay 0 --max-delay 0

Safety:
    Move mouse to top-left corner to abort (PyAutoGUI failsafe).
    Ctrl+C for graceful shutdown at any time.
"""
from __future__ import annotations

import argparse
import logging
import random
import signal
import sys
import threading
import time
from typing import Callable, Optional, TYPE_CHECKING

import pyautogui
from rich import box
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

import config as cfg_module
import module_input
import module_tabs
import profiles as profiles_module

if TYPE_CHECKING:
    from ui_window import MacroStatusWindow
    from settings_window import MacroConfig

# ── Console ───────────────────────────────────────────────────────────────────

console = Console()

# ── Logging ───────────────────────────────────────────────────────────────────

_file_handler = logging.FileHandler("macro_run.log", encoding="utf-8")
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(console=console, rich_tracebacks=True, show_path=False),
        _file_handler,
    ],
)
logger = logging.getLogger("orchestrator")

# ── Action registries ─────────────────────────────────────────────────────────
# (name, callable, default weight)

INPUT_REGISTRY: list[tuple[str, Callable[[], None], int]] = [
    ("simulate_mouse_move",       module_input.simulate_mouse_move,       40),
    ("simulate_scroll",           module_input.simulate_scroll,           30),
    ("simulate_keypress",         module_input.simulate_keypress,         15),
    ("simulate_mouse_and_scroll", module_input.simulate_mouse_and_scroll, 15),
]

TAB_REGISTRY: list[tuple[str, Callable[[], None], int]] = [
    ("switch_tab_forward",    module_tabs.switch_tab_forward,    35),
    ("switch_tab_backward",   module_tabs.switch_tab_backward,   25),
    ("switch_to_tab_number",  module_tabs.switch_to_tab_number,  20),
    ("switch_window_forward", module_tabs.switch_window_forward, 15),
    ("focus_address_bar",     module_tabs.focus_address_bar,      5),
]

# ── Defaults (used in --no-gui mode) ─────────────────────────────────────────

DEFAULT_MIN_DELAY: int      = 5
DEFAULT_MAX_DELAY: int      = 10
DEFAULT_APC: int            = 5
DEFAULT_INPUT_WEIGHT: int   = 60
DEFAULT_TAB_WEIGHT: int     = 40

INTRA_ACTION_DELAY: tuple[float, float] = (1.0, 3.0)

# ── Run statistics ────────────────────────────────────────────────────────────

class RunStats:
    def __init__(self) -> None:
        self.start_time    = time.time()
        self.cycles_done   = 0
        self.total_actions = 0
        self.action_counts: dict[str, int] = {}
        self.errors        = 0

    def record(self, name: str) -> None:
        self.total_actions += 1
        self.action_counts[name] = self.action_counts.get(name, 0) + 1

    def elapsed_str(self) -> str:
        s = int(time.time() - self.start_time)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}h {m:02d}m {sec:02d}s" if h else f"{m}m {sec:02d}s"

    def last_action(self) -> str:
        if not self.action_counts:
            return "—"
        return max(self.action_counts, key=lambda k: self.action_counts[k])


_stats  = RunStats()
_paused = threading.Event()   # Set = paused
_stop   = threading.Event()   # Set = stop requested
_window: Optional["MacroStatusWindow"] = None


# ── Action pool builder ───────────────────────────────────────────────────────

ActionPool = list[tuple[Callable[[], None], str]]   # (fn, action_name)


def build_pool(
    input_weight: int,
    tab_weight: int,
    enabled_actions: Optional[set[str]] = None,
) -> ActionPool:
    """
    Build a weighted flat pool of (callable, name) pairs.
    Respects the input/tab weight ratio and skips any disabled actions.
    """
    all_actions = (enabled_actions
                   if enabled_actions is not None
                   else {n for n, _, _ in INPUT_REGISTRY + TAB_REGISTRY})

    pool: ActionPool = []

    # Input actions
    if input_weight > 0:
        active = [(n, fn, w) for n, fn, w in INPUT_REGISTRY if n in all_actions]
        if active:
            total_w = sum(w for _, _, w in active)
            for name, fn, w in active:
                count = max(1, round(w / total_w * input_weight))
                pool += [(fn, name)] * count

    # Tab actions
    if tab_weight > 0:
        active = [(n, fn, w) for n, fn, w in TAB_REGISTRY if n in all_actions]
        if active:
            total_w = sum(w for _, _, w in active)
            for name, fn, w in active:
                count = max(1, round(w / total_w * tab_weight))
                pool += [(fn, name)] * count

    if not pool:
        raise ValueError("No actions in pool — check enabled actions and weights.")

    return pool


def weight_to_pct(w: int, total: int) -> float:
    return round(w / total * 100, 1) if total else 0.0

# ── Shared helpers ────────────────────────────────────────────────────────────

def _fmt_seconds(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec:02d}s"


def _wait_if_paused() -> None:
    while _paused.is_set():
        time.sleep(0.5)


def _update_window(status: str, cycle: int) -> None:
    if _window is not None:
        _window.update(
            status=status,
            cycle=cycle,
            actions=_stats.total_actions,
            errors=_stats.errors,
            last_action=_stats.last_action(),
        )


# ── Pause listener (terminal / --no-gui mode) ─────────────────────────────────

def _start_pause_listener() -> None:
    def _listen() -> None:
        while True:
            try:
                line = sys.stdin.readline().strip().lower()
                if line in ("p", "pause"):
                    _paused.set()
                    console.print("\n[bold yellow]⏸  PAUSED[/]  — type [bold]r[/] + Enter to resume")
                elif line in ("r", "resume"):
                    _paused.clear()
                    console.print("[bold green]▶  RESUMED[/]")
            except (EOFError, OSError):
                break
    threading.Thread(target=_listen, daemon=True).start()


# ── Cycle runner ──────────────────────────────────────────────────────────────

def _run_cycle(
    cycle_num: int,
    actions_per_cycle: int,
    action_pool: ActionPool,
    dry_run: bool = False,
) -> None:
    logger.info("── Cycle %d started (%d actions) ──", cycle_num, actions_per_cycle)

    for step in range(1, actions_per_cycle + 1):
        if _stop.is_set():
            return
        _wait_if_paused()

        action_fn, name = random.choice(action_pool)

        if dry_run:
            _stats.record(name)
            logger.info("  [%d/%d] → [DRY RUN] %s", step, actions_per_cycle, name)
        else:
            try:
                action_fn()
                _stats.record(name)
                logger.info("  [%d/%d] → %s", step, actions_per_cycle, name)
            except pyautogui.FailSafeException:
                logger.warning("Failsafe triggered — mouse moved to corner.")
                raise
            except Exception as exc:
                _stats.errors += 1
                logger.warning("  [%d/%d] Action failed (%s): %s", step, actions_per_cycle, name, exc)

        _update_window("Running", cycle_num)

        if step < actions_per_cycle:
            time.sleep(round(random.uniform(*INTRA_ACTION_DELAY), 2))

    _stats.cycles_done += 1
    logger.info("── Cycle %d complete ──", cycle_num)


# ── Idle countdown ────────────────────────────────────────────────────────────

def _idle(min_minutes: int, max_minutes: int, cycle_num: int) -> None:
    delay = random.randint(min_minutes * 60, max_minutes * 60)
    logger.info("Idle for %s (between %dm – %dm)", _fmt_seconds(delay), min_minutes, max_minutes)
    _update_window("Idle", cycle_num)

    def _panel(remaining: int, total: int) -> Panel:
        pct    = int((total - remaining) / total * 100) if total else 100
        filled = int(pct / 100 * 32)
        bar    = "█" * filled + "░" * (32 - filled)
        return Panel(
            f"[cyan]{bar}[/]  [bold]{pct}%[/]\n\n"
            f"  Remaining  : [bold yellow]{_fmt_seconds(remaining)}[/]\n"
            f"  Total wait : [dim]{_fmt_seconds(total)}[/]\n\n"
            f"  [dim]Actions: {_stats.total_actions}  │  Cycles: {_stats.cycles_done}  │  Running: {_stats.elapsed_str()}[/]",
            title="[bold]⏳  Idle[/]", border_style="cyan",
        )

    elapsed = 0
    with Live(_panel(delay, delay), refresh_per_second=1, console=console) as live:
        while elapsed < delay:
            if _stop.is_set():
                return
            _wait_if_paused()
            time.sleep(1)
            elapsed += 1
            live.update(_panel(delay - elapsed, delay))


# ── Startup banner (terminal) ─────────────────────────────────────────────────

def _print_startup(
    min_delay: int, max_delay: int, apc: int,
    cycles: Optional[int], input_w: int, tab_w: int,
    dry_run: bool, max_seconds: Optional[int],
) -> None:
    screen_w, screen_h = pyautogui.size()
    total = input_w + tab_w
    t = Table(box=box.ROUNDED, show_header=False, padding=(0, 1), border_style="cyan")
    t.add_column("", style="bold cyan", no_wrap=True)
    t.add_column("")

    if max_seconds:
        h, rem = divmod(max_seconds, 3600)
        m, s   = divmod(rem, 60)
        dur_str = f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"
        t.add_row("Duration",        f"{dur_str} max")
    elif cycles:
        t.add_row("Cycles",          str(cycles))
    else:
        t.add_row("Cycles",          "∞  (indefinite)")

    t.add_row("Screen",          f"{screen_w} × {screen_h}")
    t.add_row("Delay range",     f"{min_delay}m – {max_delay}m per cycle")
    t.add_row("Actions / cycle", str(apc))
    t.add_row("Input weight",    f"{weight_to_pct(input_w, total)}%  ({input_w})")
    t.add_row("Tab weight",      f"{weight_to_pct(tab_w,   total)}%  ({tab_w})")
    if dry_run:
        t.add_row("Dry run",     "[bold red]YES — no real actions[/]")
    t.add_row("Failsafe",        "[bold green]ENABLED[/] — move mouse to top-left to abort")

    console.print(Panel(t, title="[bold cyan]UI Macro Automation Tool[/bold cyan]", border_style="cyan"))


# ── Summary ───────────────────────────────────────────────────────────────────

def _print_summary(stats: RunStats) -> None:
    t = Table(title="[bold]Run Summary[/bold]", box=box.ROUNDED,
              border_style="green", padding=(0, 1))
    t.add_column("Metric", style="bold cyan", no_wrap=True)
    t.add_column("Value")
    t.add_row("Total cycles",  str(stats.cycles_done))
    t.add_row("Total actions", str(stats.total_actions))
    t.add_row("Errors",        f"[red]{stats.errors}[/]" if stats.errors else "0")
    t.add_row("Total time",    stats.elapsed_str())
    if stats.action_counts:
        t.add_section()
        for action, count in sorted(stats.action_counts.items(), key=lambda x: -x[1]):
            pct = round(count / stats.total_actions * 100, 1) if stats.total_actions else 0
            t.add_row(f"  {action}", f"{count}  ({pct}%)")
    console.print(t)


# ── Core loop (runs on main thread or background thread) ──────────────────────

def _run_loop(
    action_pool: ActionPool,
    min_delay: int,
    max_delay: int,
    actions_per_cycle: int,
    cycles_limit: Optional[int],
    max_seconds: Optional[int],
    dry_run: bool,
) -> None:
    if dry_run:
        console.print(Panel(
            "[bold yellow]DRY RUN MODE[/bold yellow]\n"
            "[dim]No real mouse, scroll, or keypress actions will occur.[/dim]",
            border_style="yellow",
        ))

    logger.info("Starting in 3 seconds … (Ctrl+C or Stop to cancel)")
    time.sleep(3)

    if _window is None:
        _start_pause_listener()
        console.print("  [dim]Pause: [bold]p[/] + Enter  │  Resume: [bold]r[/] + Enter  │  Stop: Ctrl+C[/dim]\n")

    cycle_num = 0
    loop_start = time.time()

    try:
        while not _stop.is_set():

            # Duration-based stop
            if max_seconds and (time.time() - loop_start) >= max_seconds:
                logger.info("Duration limit reached. Exiting.")
                break

            cycle_num += 1
            _run_cycle(cycle_num, actions_per_cycle, action_pool, dry_run)

            if _stop.is_set():
                break

            # Cycle-count stop
            if cycles_limit and cycle_num >= cycles_limit:
                logger.info("Reached cycle limit (%d). Exiting.", cycles_limit)
                break

            _idle(min_delay, max_delay, cycle_num)

    except pyautogui.FailSafeException:
        logger.info("Terminated via failsafe. Cycles completed: %d", cycle_num)
        _print_summary(_stats)
        if _window:
            _window.update("Stopped", cycle_num, _stats.total_actions, _stats.errors, "—")
            _window.close()
        sys.exit(0)

    logger.info("Automation complete. Cycles run: %d", cycle_num)
    _print_summary(_stats)
    if _window:
        _window.update("Complete", cycle_num, _stats.total_actions, _stats.errors, "—")
        _window.close()


# ── CLI (--no-gui mode only) ──────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="UI macro tool. Run without flags to open the settings GUI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--no-gui",        action="store_true",  help="Terminal mode — skip both windows")
    p.add_argument("--list-profiles", action="store_true",  help="Print profiles and exit")
    p.add_argument("--profile",       choices=profiles_module.list_profiles(), metavar="NAME")
    p.add_argument("--min-delay",     type=int, default=None, metavar="MIN")
    p.add_argument("--max-delay",     type=int, default=None, metavar="MIN")
    p.add_argument("--actions-per-cycle", type=int, default=None, metavar="N")
    p.add_argument("--cycles",        type=int, default=None, metavar="N")
    p.add_argument("--input-weight",  type=int, default=None, metavar="W")
    p.add_argument("--tab-weight",    type=int, default=None, metavar="W")
    p.add_argument("--dry-run",       action="store_true")
    p.add_argument("--save-config",   action="store_true")
    p.add_argument("--reset-config",  action="store_true")
    p.add_argument("--verbose",       action="store_true")
    p.add_argument("--quiet",         action="store_true")
    return p


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    global _stats, _window
    _stats = RunStats()
    _stop.clear()
    _paused.clear()

    parsed = _build_parser().parse_args()

    if parsed.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif parsed.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    # --list-profiles
    if parsed.list_profiles:
        t = Table("Profile", "Description", "Actions/cycle", "Delay",
                  box=box.ROUNDED, border_style="cyan", header_style="bold cyan")
        for name, data in profiles_module.PROFILES.items():
            t.add_row(f"[bold]{name}[/]", data["description"],
                      str(data["actions_per_cycle"]), f"{data['min_delay']}–{data['max_delay']}m")
        console.print(t)
        sys.exit(0)

    # --reset-config
    if parsed.reset_config:
        deleted = cfg_module.delete()
        console.print("[green]✓ config.json deleted.[/]" if deleted
                      else "[yellow]No config.json found.[/]")
        sys.exit(0)

    # Graceful Ctrl+C
    def _sigint(sig, frame):
        console.print("\n[bold red]Interrupt — shutting down.[/bold red]")
        _stop.set()
        _paused.clear()
        _print_summary(_stats)
        if _window:
            _window.close()
        sys.exit(0)
    signal.signal(signal.SIGINT, _sigint)

    # ══════════════════════════════════════════════════════════════════════════
    # GUI MODE  (default — shows settings window, then status window)
    # ══════════════════════════════════════════════════════════════════════════
    if not parsed.no_gui:
        from license_manager import LicenseManager
        from license_window import LicenseWindow
        from settings_window import MacroConfig, SettingsWindow
        from ui_window import MacroStatusWindow

        # ── License check ─────────────────────────────────────────────────────
        lm = LicenseManager()
        cached = lm.check_cached()
        if not cached.success:
            # Show activation window; exit if user cancels
            activated = LicenseWindow().run()
            if not activated:
                sys.exit(0)

        # Pre-fill form from config.json if present
        saved = cfg_module.load()
        initial = MacroConfig(
            min_delay         = saved.get("min_delay",         DEFAULT_MIN_DELAY),
            max_delay         = saved.get("max_delay",         DEFAULT_MAX_DELAY),
            actions_per_cycle = saved.get("actions_per_cycle", DEFAULT_APC),
            input_weight      = saved.get("input_weight",      DEFAULT_INPUT_WEIGHT),
            tab_weight        = saved.get("tab_weight",        DEFAULT_TAB_WEIGHT),
            cycles            = saved.get("cycles"),
        )
        if initial.cycles:
            initial.run_mode = "cycles"

        # 1. Show settings form (blocks until Start or close)
        cfg = SettingsWindow(initial=initial).run()
        if cfg is None:
            sys.exit(0)          # user closed the form without starting

        # 2. Build action pool from form values
        action_pool = build_pool(cfg.input_weight, cfg.tab_weight, cfg.enabled_actions)

        _print_startup(
            cfg.min_delay, cfg.max_delay, cfg.actions_per_cycle,
            cfg.cycles, cfg.input_weight, cfg.tab_weight,
            cfg.dry_run, cfg.max_duration_seconds(),
        )

        # 3. Build config dict for the status window header
        window_cfg = {
            "min_delay":         cfg.min_delay,
            "max_delay":         cfg.max_delay,
            "actions_per_cycle": cfg.actions_per_cycle,
            "cycles":            cfg.cycles,
            "input_weight":      cfg.input_weight,
            "tab_weight":        cfg.tab_weight,
            "dry_run":           cfg.dry_run,
        }

        # 4. Open status window
        window = MacroStatusWindow(window_cfg, _paused, _stop)
        _window = window

        gui_handler = window.make_log_handler()
        gui_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(gui_handler)

        # 5. Run macro loop in background thread
        def _macro():
            _run_loop(
                action_pool       = action_pool,
                min_delay         = cfg.min_delay,
                max_delay         = cfg.max_delay,
                actions_per_cycle = cfg.actions_per_cycle,
                cycles_limit      = cfg.cycles,
                max_seconds       = cfg.max_duration_seconds(),
                dry_run           = cfg.dry_run,
            )

        threading.Thread(target=_macro, daemon=True).start()
        window.run()   # blocks main thread until window closes
        return

    # ══════════════════════════════════════════════════════════════════════════
    # HEADLESS / --no-gui MODE  (uses CLI flags + config.json)
    # ══════════════════════════════════════════════════════════════════════════

    # Resolve settings: profile → config.json → defaults → CLI overrides
    resolved = {
        "min_delay":         DEFAULT_MIN_DELAY,
        "max_delay":         DEFAULT_MAX_DELAY,
        "actions_per_cycle": DEFAULT_APC,
        "input_weight":      DEFAULT_INPUT_WEIGHT,
        "tab_weight":        DEFAULT_TAB_WEIGHT,
        "cycles":            None,
        "dry_run":           False,
    }
    if parsed.profile:
        pd = profiles_module.get(parsed.profile)
        if pd:
            resolved.update(pd)
    resolved.update(cfg_module.load())
    for key in ("min_delay", "max_delay", "actions_per_cycle", "input_weight", "tab_weight", "cycles"):
        val = getattr(parsed, key, None)
        if val is not None:
            resolved[key] = val
    if parsed.dry_run:
        resolved["dry_run"] = True

    min_d  = resolved["min_delay"]
    max_d  = resolved["max_delay"]
    apc    = resolved["actions_per_cycle"]
    iw     = resolved["input_weight"]
    tw     = resolved["tab_weight"]
    cycles = resolved["cycles"]
    dryrun = resolved["dry_run"]

    errors: list[str] = []
    if min_d > max_d:            errors.append("--min-delay must be ≤ --max-delay")
    if apc < 1:                   errors.append("--actions-per-cycle must be ≥ 1")
    if iw == 0 and tw == 0:      errors.append("--input-weight and --tab-weight cannot both be 0")
    if errors:
        for e in errors:
            console.print(f"[bold red]Error:[/] {e}")
        sys.exit(1)

    if parsed.save_config:
        cfg_module.save({"min_delay": min_d, "max_delay": max_d,
                         "actions_per_cycle": apc, "input_weight": iw, "tab_weight": tw})
        console.print("[green]✓ Saved to config.json[/green]")

    action_pool = build_pool(iw, tw)
    _print_startup(min_d, max_d, apc, cycles, iw, tw, dryrun, None)
    _run_loop(action_pool, min_d, max_d, apc, cycles, None, dryrun)


if __name__ == "__main__":
    main()
