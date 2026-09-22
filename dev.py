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
    """Re-launch as admin if needed. Exits current process if re-launching.

    用 SW_HIDE (0) 替代 SW_SHOWNORMAL (1) 作为 nShowCmd,
    避免已经 UAC 提权过的进程被 runas verb 唤起的黑色 console 闪一下。
    """
    if sys.platform != "win32":
        return
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    _log("re-launching as admin ...")
    # 0 = SW_HIDE:不显示提权弹窗以外的额外窗口(避免一闪而过的 cmd 框)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{__file__}"', None, 0,
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# PySide6 check
# ---------------------------------------------------------------------------


def _ensure_deps():
    """Install required packages if missing.

    Windows 下走 CREATE_NO_WINDOW 标志,避免 pip install 弹一个黑色 cmd 窗口一闪而过。
    """
    deps = [
        ("PySide6", "PySide6"),
        ("yaml", "PyYAML"),
        ("numpy", "numpy"),
        ("cv2", "opencv-python"),
        ("dxcam", "dxcam"),
        ("rapidocr_onnxruntime", "rapidocr_onnxruntime"),
        ("pypinyin", "pypinyin"),
        ("requests", "requests"),  # 价格查询重构后引入(2026-08-07)
    ]
    pip_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        # 0x08000000 = CREATE_NO_WINDOW:子进程不继承 console,避免黑色 cmd 框闪一下
        pip_kwargs["creationflags"] = 0x08000000

    for import_name, pip_name in deps:
        try:
            __import__(import_name)
        except ImportError:
            _log(f"installing {pip_name} ...")
            # 用 venv 的 python 启动 pip(若存在),保证依赖装到 venv,
            # 避免污染用户系统 site-packages。
            py = _venv_python()
            if py != sys.executable:
                _log(f"  via {py}")
            subprocess.check_call(
                [py, "-m", "pip", "install", pip_name,
                 "--no-warn-script-location", "--quiet"],
                **pip_kwargs,
            )
            _log(f"{pip_name} installed.")


# ===========================================================================
#  Child process — runs the actual Qt app
# ===========================================================================


def run_child():
    """Entry point for --child. Runs Qt app with reload-signal polling."""

    # --- 打包(windowed)环境兜底 --------------------------------------------
    # PyInstaller --windowed 启动时 stdout/stderr 有两种异常形态:
    #   ① 双击启动 → 句柄无效 → 流为 None → 直接 .write() 触发
    #      'NoneType' object has no attribute 'write' 崩溃
    #      (app_shell/trigger_manager/triggers_page/cd_debug_log 多处)。
    #      → 统一换向到用户日志目录 console.log,便于用户反馈问题。
    #   ② CMD 启动 / 管道启动 → 句柄有效但编码为 GBK(cp936)→
    #      输出 '✓'(U+2713)等字符触发 UnicodeEncodeError
    #      (app_shell._register_pages)。
    #      → 强制 reconfigure 为 UTF-8 + errors='replace'。
    if getattr(sys, "frozen", False):
        # ② 先处理编码:流可能非 None,GBK 无法编码 ✓/· 等字符
        for _stream in (sys.stdout, sys.stderr):
            if _stream is not None and hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
                except (OSError, ValueError):
                    pass  # reconfigure 失败不影响启动,后续写入按原编码降级
        # ① 再处理 None:换向 console.log(UTF-8 行缓冲)
        if sys.stdout is None or sys.stderr is None:
            try:
                from core.paths import user_data_dir
                log_dir = user_data_dir() / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                console = open(log_dir / "console.log", "a", encoding="utf-8", buffering=1)
            except OSError:
                console = None
            if console is None:
                console = open(os.devnull, "w", encoding="utf-8")
            if sys.stdout is None:
                sys.stdout = console
            if sys.stderr is None:
                sys.stderr = console

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
    # 注:theme_proxy 导入必须提前到 try 之前 — 下方 if/else 两个分支都依赖这些常量,
    # 若在 else 内 import,Python 编译期会把整个函数体里的 COLOR_BLACK 标记为 local,
    # 导致 _preset_loaded=True 分支内 line 160 报 UnboundLocalError(import-as-binding)。
    from core.theme_proxy import PANEL_BG, LIGHT_TEXT, CARD_BG, CYBER_YELLOW, COLOR_BLACK
    try:
        tm.load_preset("cyberpunk")
        _preset_loaded = True
    except Exception as e:
        _log(f"[warn] load_preset failed: {e}")

    if _preset_loaded:
        # token key 走新 alias 路径;无 hex 字面量,符合 F1 规范
        base = QColor(tm.get("alias.bg.base"))
        text = QColor(tm.get("alias.text.primary"))
        raised = QColor(tm.get("alias.bg.raised"))
        accent = QColor(tm.get("alias.accent.primary"))
    else:
        # token 加载失败的极端 fallback,走 theme_proxy 代理常量(自身零硬编码)
        base = QColor(str(PANEL_BG))
        text = QColor(str(LIGHT_TEXT))
        raised = QColor(str(CARD_BG))
        accent = QColor(str(CYBER_YELLOW))

    palette.setColor(QPalette.ColorRole.Window, base)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, raised)
    # AlternateBase 取最深背景(text.inverse,值为 #111122,符合 dark mode 风格)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(str(COLOR_BLACK)))
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

    # --- 退出前清理:等待所有 QThread 子类(PriceFetcher/CacheWarmer 等)正常退出 ----
    # 问题:app.quit() 后 Python 解释器立刻回收对象,
    # 但某些子线程(如 PriceFetcher 正在做 HTTP 请求)仍在跑,
    # 触发 "QThread: Destroyed while thread '' is still running"
    # 甚至导致 STATUS_STACK_BUFFER_OVERRUN (0xC0000409) 崩溃。
    # 修法:在 aboutToQuit 时遍历所有活跃 QThread,给 1s 优雅退出窗口。
    from PySide6.QtCore import QThread

    def _wait_for_qthreads():
        """等待所有活跃 QThread 完成(给 1s 宽限)。"""
        deadline = time.time() + 1.0
        app.processEvents()
        for th in QApplication.instance().findChildren(QThread):
            if th is QThread.currentThread():
                continue
            if th.isRunning():
                th.quit()  # 请求事件循环退出
                th.wait(max(0, deadline - time.time()))
        # 最后再 processEvents 一次,让 queued 信号完成
        app.processEvents()

    app.aboutToQuit.connect(_wait_for_qthreads)

    # --- Run ---------------------------------------------------------------
    sys.exit(app.exec())


# ===========================================================================
#  Parent process — watches files, manages child lifecycle
# ===========================================================================


def _venv_python() -> str:
    """返回 venv 里的 python.exe 路径(若存在),否则返回当前 sys.executable。

    用途:child 进程必须用同一个 Python 解释器(否则 site-packages 不共享)。
    如果 dev.py 是用 venv 里的 python 启动的,venv_python() == sys.executable;
    如果是用系统 python 启动的,但项目自带 venv,则切到 venv 的 python(避免
    依赖装到系统 site-packages,污染用户环境)。
    """
    if sys.platform == "win32":
        venv_py = PROJECT_DIR / "venv" / "Scripts" / "python.exe"
    else:
        venv_py = PROJECT_DIR / "venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _start_child():
    """Spawn child process. Returns Popen handle.

    Windows 下通过 Job Object 绑定父进程:父进程被 kill/关窗/CTRL_CLOSE_EVENT 时,
    内核会自动结束 child 进程,避免出现孤儿进程(主程序残留但日志窗口没了)。

    这样做的好处:
      1. 用户关掉 dev.py 的常驻 CMD 窗口 → 父进程退出 → child 被 Job Object 自动收尸
      2. 父进程崩溃 / 被任务管理器结束 → 同上
      3. 正常 Ctrl+C → 走优雅 reload 信号 + closeAllWindows,子进程 Qt 资源能清理

    Job Object 标志(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE):
      当父进程最后一句 handle 关闭时,所有关联的子进程一并结束。
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    kwargs: dict = {
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        # 只用 CREATE_NO_WINDOW:子进程不创建控制台窗口(修复点)
        # 旧代码叠加了 DETACHED_PROCESS(0x8),但微软文档规定
        # CREATE_NO_WINDOW / DETACHED_PROCESS / CREATE_NEW_CONSOLE 三者互斥,
        # 组合使用行为未定义 → 部分 Windows 上反而弹出一个标题为
        # "venv\Scripts\python.exe" 的空 CMD 窗口
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        kwargs["stdin"] = subprocess.DEVNULL

    # 关键:用 venv 的 python(若存在)启动 child,避免系统 Python 找不到
    # 项目专属依赖(如 requests)。如果 dev.py 自己就是 venv 启动的,
    # _venv_python() == sys.executable,行为不变。
    py = _venv_python()
    if py != sys.executable:
        _log(f"using venv python: {py}")
    proc = subprocess.Popen(
        [py, "-u", __file__, "--child"], **kwargs
    )

    if sys.platform == "win32":
        _bind_to_job_object(proc)
    return proc


# ---------------------------------------------------------------------------
#  Windows Job Object — 父进程退出时自动带走子进程
# ---------------------------------------------------------------------------

# Windows WinNT 头文件常量(避免额外依赖 pywin32)
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


def _bind_to_job_object(proc: subprocess.Popen) -> None:
    """把 child 进程 attach 到一个 Job Object。

    Job Object 设置 KILL_ON_JOB_CLOSE 标志:父进程最后 handle 关闭时,内核自动
    TerminateProcess 所有关联子进程。覆盖场景:
      - 用户关掉 dev.py 的 CMD 窗口
      - 父进程崩溃 / 被任务管理器结束
      - 父进程 SIGINT / SIGTERM
    """
    import ctypes
    from ctypes import wintypes

    try:
        kernel32 = ctypes.windll.kernel32

        # 1. 创建 Job Object
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return  # 失败静默:不影响主流程,只是失去兜底保护

        # 2. 设置扩展限制信息(KILL_ON_JOB_CLOSE)
        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        info_ptr = ctypes.byref(info)
        info_size = ctypes.sizeof(info)
        ret = kernel32.SetInformationJobObject(
            job,
            _JobObjectExtendedLimitInformation,
            info_ptr,
            info_size,
        )
        if not ret:
            kernel32.CloseHandle(job)
            return

        # 3. 把子进程加入 Job(需要 PROCESS_SET_QUOTA + PROCESS_TERMINATE 权限)
        proc_handle = int(proc._handle)  # Popen 内部句柄
        ret = kernel32.AssignProcessToJobObject(job, proc_handle)
        if not ret:
            kernel32.CloseHandle(job)
            return

        # 4. 保存 job handle 到进程对象,避免被 GC 回收导致 flag 失效
        # 父进程持有 handle 期间,child 不会被结束;
        # 父进程退出(handle 自动 close),内核收尸 child。
        proc._cyber_job_handle = job  # type: ignore[attr-defined]

    except Exception as e:
        # Job Object 是兜底保护,失败也不应阻塞 dev 启动
        _log(f"[warn] bind job object failed: {e}")


# ---------------------------------------------------------------------------
#  父进程退出时的优雅清理 — 父进程信号 → 发 reload → child 退出 → 父进程退出
# ---------------------------------------------------------------------------


def _shutdown_child(proc: subprocess.Popen, timeout: float = 3.0) -> None:
    """通知 child 优雅退出(走 reload 信号 → Qt closeAllWindows → quit)。"""
    try:
        RELOAD_SIGNAL.touch()
    except OSError:
        pass
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _log("WARNING: child did not exit gracefully, forcing kill")
        proc.kill()
        proc.wait(timeout=2)


def _install_signal_handlers(proc_ref: list) -> None:
    """注册 SIGINT/SIGTERM handler:父进程收到退出信号时,优雅通知 child。

    Windows 下 SIGINT 来自 Ctrl+C / Ctrl+Break(在 CMD 窗口按 Ctrl+C);
    用户点窗口的关闭按钮 → 触发 CTRL_CLOSE_EVENT,Python 默认会发 SIGBREAK。
    """
    import signal

    def _handler(sig, frame):
        proc = proc_ref[0] if proc_ref else None
        if proc is not None:
            _log(f"[exit] signal {sig} received, closing child ...")
            _shutdown_child(proc, timeout=2.0)
        # 重新抛默认行为,让父进程正常退出
        raise KeyboardInterrupt()

    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):
        pass
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass
    # Windows: 关闭 CMD 窗口 → CTRL_CLOSE_EVENT → Python 收到 SIGBREAK
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, _handler)
        except (ValueError, OSError):
            pass


def _install_windows_close_handler(proc_ref: list) -> None:
    """Windows 控制台关闭事件:用户点 CMD 窗口的 X 关闭按钮时触发。

    走 SetConsoleCtrlHandler 注册回调,收到 CTRL_CLOSE_EVENT / CTRL_LOGOFF_EVENT
    / CTRL_SHUTDOWN_EVENT 时,先发 reload 信号让 child 走 Qt 优雅退出,再 return False
    走默认处理(终止父进程)。Job Object 兜底保证即便 child 没能及时响应,父死
    child 也会被内核 kill。
    """
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    CTRL_C_EVENT = 0
    CTRL_BREAK_EVENT = 1
    CTRL_CLOSE_EVENT = 2
    CTRL_LOGOFF_EVENT = 5
    CTRL_SHUTDOWN_EVENT = 6

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def _handler(ctrl_type: int) -> bool:
        proc = proc_ref[0] if proc_ref else None
        if proc is None:
            return False
        if ctrl_type in (CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            _log(f"[exit] console close event {ctrl_type}, closing child ...")
            _shutdown_child(proc, timeout=2.0)
        # return False → 系统执行默认处理(终止父进程);child 已被 Job Object 兜底
        return False

    try:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True)
    except Exception as e:
        _log(f"[warn] SetConsoleCtrlHandler failed: {e}")


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
    """Main watch loop – never calls proc.kill() (except in shutdown)."""

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
    _log("  关闭此 CMD 窗口将自动关闭主程序 (Job Object 兜底)")
    _log("=" * 50)

    proc = _start_child()
    threading.Thread(target=_pipe_reader, args=(proc,), daemon=True).start()

    # ── 退出兜底:信号 / 控制台关闭 → child 优雅退出 ──
    # 用 list 包引用,因为 signal handler 不能捕获赋值
    proc_ref: list = [proc]
    _install_signal_handlers(proc_ref)
    _install_windows_close_handler(proc_ref)

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
                proc_ref[0] = proc
                threading.Thread(target=_pipe_reader, args=(proc,),
                                 daemon=True).start()
                # 重启后重新注册 close handler(新 child)
                _install_windows_close_handler(proc_ref)
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
            proc_ref[0] = proc
            threading.Thread(target=_pipe_reader, args=(proc,),
                             daemon=True).start()
            _install_windows_close_handler(proc_ref)

    except KeyboardInterrupt:
        _log("stopping ...")
        _shutdown_child(proc_ref[0] if proc_ref else proc, timeout=5.0)
        _log("done.")


# ===========================================================================
#  main
# ===========================================================================


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--trae")]
    frozen = getattr(sys, "frozen", False)

    if "--child" in args:
        # Child process: run the Qt app
        run_child()
        return

    if "--once" in args:
        # One-shot launch
        if not frozen:
            _ensure_admin()
            _ensure_deps()
        run_child()
        return

    # Default: watch mode
    if frozen:
        # 打包后直接运行
        run_child()
        return
    _ensure_admin()
    _ensure_deps()
    try:
        run_watch()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()