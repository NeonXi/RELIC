"""
dev.py - Hot Reload Launcher
============================
Replaces dev.bat. Single entry point for development.

Flow:
    python dev.py
        → admin elevation
        → PySide6 check
        → spawn child: python dev.py --child
        → watch files, restart on change

Reload mechanism:
    Parent touches ".reload" file → Child's QTimer detects it →
    Child gracefully quits Qt (closeAllWindows + quit) → Parent spawns new child.
    No TerminateProcess, no orphaned windows.

Usage:
    python dev.py           # Watch mode (auto-restart on file change)
    python dev.py --once    # Single launch, no watch
"""
import sys
import os
import time
import subprocess
import threading
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parent
RELOAD_SIGNAL = PROJECT_DIR / ".reload"
WATCH_EXTS = {".py", ".yaml", ".yml"}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(msg: str):
    print(f"[{_ts()}] {msg}", flush=True)


def _get_mtimes() -> dict:
    """Snapshot of project file modification times."""
    skip = {"venv", ".git", "__pycache__", ".codebuddy", "dist",
            "build", "testvenv", "tests", ".trae"}
    mtimes = {}
    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if Path(f).suffix not in WATCH_EXTS:
                continue
            path = os.path.join(root, f)
            try:
                mtimes[path] = os.path.getmtime(path)
            except OSError:
                pass
    return mtimes


# ---------------------------------------------------------------------------
# admin elevation
# ---------------------------------------------------------------------------


def _ensure_admin():
    """Re-launch as admin if needed. Exits current process if re-launching."""
    if sys.platform != "win32":
        return
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    _log("re-launching as admin ...")
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, __file__, None, 1,
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# PySide6 check
# ---------------------------------------------------------------------------


def _ensure_deps():
    """Install required packages if missing."""
    deps = [
        ("PySide6", "PySide6"),
        ("yaml", "PyYAML"),
        ("numpy", "numpy"),
        ("cv2", "opencv-python"),
        ("dxcam", "dxcam"),
        ("rapidocr_onnxruntime", "rapidocr_onnxruntime"),
    ]
    for import_name, pip_name in deps:
        try:
            __import__(import_name)
        except ImportError:
            _log(f"installing {pip_name} ...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", pip_name, "-q"])
            _log(f"{pip_name} installed.")


# ===========================================================================
#  Child process — runs the actual Qt app
# ===========================================================================


def run_child():
    """Entry point for --child. Runs Qt app with reload-signal polling."""

    # --- Qt env ------------------------------------------------------------
    os.environ["QT_QPA_PLATFORM"] = "windows:dpiawareness=0"
    os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.*.warning=false"

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPalette, QColor
    from core.tokens.manager import TokenManager
    from core.app_shell import AppShell

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # --- palette -----------------------------------------------------------
    palette = QPalette()
    tm = TokenManager.instance()
    _preset_loaded = False
    try:
        tm.load_preset("cyberpunk")
        _preset_loaded = True
    except Exception as e:
        _log(f"[warn] load_preset failed: {e}")

    if _preset_loaded:
        base = QColor(tm.get("surface.base", "#08081A"))
        text = QColor(tm.get("text.primary", "#E8ECFF"))
        raised = QColor(tm.get("surface.raised", "#0E0E24"))
        accent = QColor(tm.get("accent.primary", "#FFE600"))
    else:
        base = QColor("#08081A")
        text = QColor("#E8ECFF")
        raised = QColor("#0E0E24")
        accent = QColor("#FFE600")

    palette.setColor(QPalette.ColorRole.Window, base)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, raised)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#111122"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, raised)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, base)
    app.setPalette(palette)

    _log("AppShell launched")
    _log(f"  preset: {tm.current_preset if _preset_loaded else 'fallback'}")

    window = AppShell(show_splash=True)

    # --- Reload-signal poll timer ------------------------------------------
    # Every 500 ms check if parent wants us to restart.
    def _poll_reload():
        if RELOAD_SIGNAL.exists():
            _log("[reload] signal detected, quitting ...")
            try:
                RELOAD_SIGNAL.unlink()
            except OSError:
                pass
            reload_timer.stop()
            app.closeAllWindows()
            app.quit()

    reload_timer = QTimer()
    reload_timer.timeout.connect(_poll_reload)
    reload_timer.start(500)

    # --- Handle external kill signals gracefully ---------------------------
    import signal

    def _on_signal(sig, frame):
        _log("[exit] signal received, closing windows ...")
        app.closeAllWindows()
        app.quit()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    # --- Run ---------------------------------------------------------------
    sys.exit(app.exec())


# ===========================================================================
#  Parent process — watches files, manages child lifecycle
# ===========================================================================


def _start_child():
    """Spawn child process. Returns Popen handle."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    kwargs = {
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | 0x00000008  # DETACHED_PROCESS
        )
        kwargs["stdin"] = subprocess.DEVNULL
    return subprocess.Popen(
        [sys.executable, "-u", __file__, "--child"], **kwargs
    )


def _pipe_reader(proc):
    """Read child stdout and print to parent terminal (daemon thread)."""
    while True:
        try:
            line = proc.stdout.readline()
            if not line:
                break
            print(line.decode("utf-8", errors="replace").rstrip(), flush=True)
        except Exception:
            break


def run_watch():
    """Main watch loop – never calls proc.kill()."""

    # Clean up stale signal from previous crashed run
    try:
        RELOAD_SIGNAL.unlink()
    except OSError:
        pass

    _log("=" * 50)
    _log("DEV MODE (hot reload)")
    _log(f"  dir:   {PROJECT_DIR}")
    _log(f"  watch: {', '.join(sorted(WATCH_EXTS))}")
    _log("  Ctrl+C to exit")
    _log("=" * 50)

    proc = _start_child()
    threading.Thread(target=_pipe_reader, args=(proc,), daemon=True).start()
    last_mtimes = _get_mtimes()
    restart_count = 0

    try:
        while True:
            time.sleep(1)

            # ---- handle unexpected crash ----
            ret = proc.poll()
            if ret is not None and ret != 0:
                restart_count += 1
                _log(f"child crashed (code={ret}), restarting ...")
                time.sleep(1)
                proc = _start_child()
                threading.Thread(target=_pipe_reader, args=(proc,),
                                 daemon=True).start()
                last_mtimes = _get_mtimes()
                continue

            # ---- check for file changes ----
            current = _get_mtimes()
            if current == last_mtimes:
                continue

            changed = [os.path.relpath(p, PROJECT_DIR)
                       for p in current
                       if current[p] != last_mtimes.get(p)]
            _log(f"[change] {len(changed)} file(s), restarting ...")
            for f in changed[:3]:
                _log(f"         {f}")
            if len(changed) > 3:
                _log(f"         ... +{len(changed) - 3} more")

            last_mtimes = current
            restart_count += 1

            # ---- graceful restart (no kill!) ----
            RELOAD_SIGNAL.touch()
            try:
                proc.wait(timeout=10)
                _log(f"child exited cleanly (restart #{restart_count})")
            except subprocess.TimeoutExpired:
                _log("WARNING: child did not exit, forcing kill")
                proc.kill()
                proc.wait(timeout=5)

            proc = _start_child()
            threading.Thread(target=_pipe_reader, args=(proc,),
                             daemon=True).start()

    except KeyboardInterrupt:
        _log("stopping ...")
        RELOAD_SIGNAL.touch()
        try:
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.kill()
            proc.wait(timeout=3)
        _log("done.")


# ===========================================================================
#  main
# ===========================================================================


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--trae")]

    if "--child" in args:
        # Child process: run the Qt app
        run_child()
        return

    if "--once" in args:
        # One-shot launch
        _ensure_admin()
        _ensure_deps()
        run_child()
        return

    # Default: watch mode
    _ensure_admin()
    _ensure_deps()
    try:
        run_watch()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()