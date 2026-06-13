"""
build.py - 打包脚本
========
使用 PyInstaller 将项目打包为 onedir 格式，带进度显示。

用法:
    python build.py              # 默认打包
    python build.py --clean      # 清理旧构建后重新打包
    python build.py --no-console # 打包后不显示控制台窗口

输出:
    dist/WARFRAME-RELIC/         # onedir 文件夹
"""

import sys
import os
import shutil
import subprocess
import time
import threading
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════

PROJECT_DIR = Path(__file__).resolve().parent
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"
NAME = "WARFRAME-RELIC"
ENTRY = PROJECT_DIR / "dev.py"

# 要打包的数据目录 (src, dst)
DATA_DIRS = [
    ("assets", "assets"),
    ("data", "data"),
    ("icon", "icon"),
]

# 要打包的单独文件 (src, dst)
DATA_FILES = [
    ("qt.conf", "."),
    ("yolov5nu.pt", "."),
]

# 需要显式包含的隐藏导入
HIDDEN_IMPORTS = [
    # Qt
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    "PySide6.QtNetwork",
    # 核心依赖
    "cv2",
    "numpy",
    "pypinyin",
    "yaml",
    "PIL",
    "PIL.Image",
    "dxcam",
    "comtypes",
    "comtypes.stream",
    "rapidocr_onnxruntime",
    "rapidocr_onnxruntime.ch_ppocr_v4_rec",
    "rapidocr_onnxruntime.ch_ppocr_v4_det",
    # 项目内部模块
    "core",
    "core.app_shell",
    "core.annotation",
    "core.constants",
    "core.fonts",
    "core.hotkey_config",
    "core.hotkey_manager",
    "core.mode_handlers",
    "core.overlay",
    "core.price_service",
    "core.proxy_config",
    "core.region_selector",
    "core.theme_config",
    "core.theme_proxy",
    "core.trigger_config",
    "core.trigger_manager",
    "core.word_wrap_button",
    "core.pages",
    "core.pages.base_page",
    "core.services",
    "core.services._event_emitter",
    "core.services.db_builder",
    "core.services.db_connections",
    "core.services.item_service",
    "core.services.localization_service",
    "core.services.market_builder",
    "core.services.market_price_service",
    "core.services.pipeline",
    "core.services.repo_puller",
    "core.services.screenshot_pipeline",
    "core.recognizers",
    "core.recognizers.base_ocr",
    "core.recognizers.item_name",
    "core.recognizers.matcher",
    "core.recognizers.mod_name",
    "core.recognizers.part_mappings",
    "core.recognizers.relic_name",
    "core.state",
    "core.state.app_state",
    "core.state.event_bus",
    "core.tokens",
    "core.tokens.color_utils",
    "core.tokens.manager",
    "core.tokens.resolver",
    "core.widgets",
    "core.widgets.base",
    "core.widgets.button",
    "core.widgets.card",
    "core.widgets.combo_box",
    "core.widgets.hotkey_edit",
    "core.widgets.line_edit",
    "core.widgets.log_viewer",
    "core.widgets.manual_update_dialog",
    "core.widgets.panel",
    "core.widgets.pixel_font_editor",
    "core.widgets.proxy_dialog",
    "core.widgets.relic_tooltip",
    "core.widgets.splash_screen",
    "core.widgets.toggle_switch",
    "data",
    "data.icon_loader",
    "data.item_index",
    "data.preset_normal",
    "data.ui_strings",
    "data.wfinfo_relics",
]

# 排除的模块
EXCLUDE_MODULES = [
    "tests",
    "docs",
    "pip",
    "setuptools",
    "wheel",
]

# ══════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _log(msg: str, level: str = "info"):
    colors = {
        "info": "\033[36m",     # cyan
        "ok": "\033[32m",       # green
        "warn": "\033[33m",     # yellow
        "error": "\033[31m",    # red
        "step": "\033[35m",     # magenta
        "reset": "\033[0m",
    }
    prefix = {
        "info": "  ",
        "ok": "  ✓",
        "warn": "  ⚠",
        "error": "  ✗",
        "step": "▶",
    }
    c = colors.get(level, colors["info"])
    p = prefix.get(level, "  ")
    reset = colors["reset"]
    print(f"{c}[{_ts()}] {p} {msg}{reset}", flush=True)


class ProgressBar:
    """简易终端进度条，无外部依赖。"""

    def __init__(self, total: int, desc: str = "", width: int = 40):
        self.total = max(1, total)
        self.current = 0
        self.desc = desc
        self.width = width
        self._start_time = time.time()
        self._lock = threading.Lock()

    def update(self, n: int = 1):
        with self._lock:
            self.current = min(self.total, self.current + n)
            self._render()

    def set(self, value: int):
        with self._lock:
            self.current = min(self.total, value)
            self._render()

    def _render(self):
        pct = self.current / self.total
        filled = int(self.width * pct)
        bar = "█" * filled + "░" * (self.width - filled)
        elapsed = time.time() - self._start_time
        if pct > 0:
            eta = elapsed / pct * (1 - pct)
            eta_str = f"{eta:.0f}s" if eta < 60 else f"{eta/60:.1f}m"
        else:
            eta_str = "..."

        print(
            f"\r  \033[36m{self.desc}\033[0m "
            f"\033[33m{bar}\033[0m "
            f"\033[37m{self.current}/{self.total}\033[0m "
            f"\033[90m[{eta_str}]\033[0m",
            end="",
            flush=True,
        )

    def finish(self, msg: str = ""):
        self.current = self.total
        self._render()
        print()  # newline
        elapsed = time.time() - self._start_time
        if msg:
            _log(f"{msg} ({elapsed:.1f}s)", "ok")
        else:
            _log(f"完成 ({elapsed:.1f}s)", "ok")


# ══════════════════════════════════════════════
# 构建步骤
# ══════════════════════════════════════════════

def step_check_pyinstaller() -> bool:
    """检查并安装 PyInstaller。"""
    _log("检查 PyInstaller ...", "step")
    try:
        import PyInstaller  # noqa: F401
        _log("PyInstaller 已就绪", "ok")
        return True
    except ImportError:
        _log("PyInstaller 未安装，正在安装 ...", "warn")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "pyinstaller",
                 "--no-warn-script-location"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _log("PyInstaller 安装完成", "ok")
            return True
        except subprocess.CalledProcessError:
            _log("PyInstaller 安装失败，请手动执行: pip install pyinstaller", "error")
            return False


def step_clean():
    """清理旧构建产物。"""
    _log("清理旧构建 ...", "step")
    for d in (DIST_DIR, BUILD_DIR):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            _log(f"  已删除 {d.name}/", "info")
    # 清理 .spec 文件
    for spec in PROJECT_DIR.glob("*.spec"):
        spec.unlink()
        _log(f"  已删除 {spec.name}", "info")
    _log("清理完成", "ok")


def step_collect_datas() -> str:
    """收集 --add-data 参数，返回 PyInstaller 参数列表。"""
    args = []
    missing = []

    for src, dst in DATA_DIRS:
        src_path = PROJECT_DIR / src
        if src_path.exists():
            args.extend(["--add-data", f"{src_path};{dst}"])
        else:
            missing.append(src)

    for src, dst in DATA_FILES:
        src_path = PROJECT_DIR / src
        if src_path.exists():
            args.extend(["--add-data", f"{src_path};{dst}"])
        else:
            missing.append(src)

    if missing:
        _log(f"以下文件/目录不存在，已跳过: {', '.join(missing)}", "warn")

    return args


def step_build(no_console: bool = False):
    """执行 PyInstaller 打包。"""
    _log("开始 PyInstaller 打包 ...", "step")

    # 收集数据文件参数
    data_args = step_collect_datas()

    # 构建 PyInstaller 命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--name", NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(PROJECT_DIR),
        "--clean",
    ]

    if no_console:
        cmd.append("--noconsole")
        cmd.append("--windowed")

    # 添加隐藏导入
    for hi in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", hi])

    # 收集整个包（含模型文件等非 Python 资源）
    cmd.extend(["--collect-all", "rapidocr_onnxruntime"])

    # 排除模块
    for em in EXCLUDE_MODULES:
        cmd.extend(["--exclude-module", em])

    # 添加数据文件
    cmd.extend(data_args)

    # 收集 core 下所有子目录的 Python 文件
    for subdir in ["pages", "services", "recognizers", "state", "tokens", "widgets"]:
        sdir = PROJECT_DIR / "core" / subdir
        if sdir.exists():
            for py_file in sdir.glob("*.py"):
                if py_file.stem != "__init__":
                    cmd.extend(["--hidden-import", f"core.{subdir}.{py_file.stem}"])

    # 入口文件
    cmd.append(str(ENTRY))

    _log(f"  输出目录: {DIST_DIR / NAME}", "info")
    _log(f"  入口文件: {ENTRY.name}", "info")
    _log(f"  no-console: {no_console}", "info")

    # 启动 PyInstaller（实时输出）
    print(f"\033[90m{'─' * 60}\033[0m", flush=True)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(PROJECT_DIR),
        )

        # 读取输出并过滤关键行
        pyi_lines = []
        last_info = ""
        for line in proc.stdout:
            line = line.rstrip()
            pyi_lines.append(line)

            # 过滤并格式化 PyInstaller 的关键信息
            line_lower = line.lower()
            if any(kw in line_lower for kw in [
                "building", "analyzing", "processing", "collecting",
                "copying", "info:", "warn", "error",
            ]):
                # 关键行高亮显示
                if "info:" in line_lower:
                    print(f"  \033[36m{line}\033[0m", flush=True)
                elif "warn" in line_lower:
                    print(f"  \033[33m{line}\033[0m", flush=True)
                elif "error" in line_lower:
                    print(f"  \033[31m{line}\033[0m", flush=True)
                else:
                    # 提取 PyInstaller 进度信息
                    short = line[line.find("INFO:") + 5:].strip() if "INFO:" in line else line
                    if short and short != last_info and len(short) < 120:
                        print(f"  \033[90m{short}\033[0m", flush=True)
                        last_info = short

        proc.wait()
        print(f"\033[90m{'─' * 60}\033[0m", flush=True)

        if proc.returncode != 0:
            _log(f"PyInstaller 打包失败 (exit code: {proc.returncode})", "error")
            # 输出最后 20 行以便调试
            _log("最后 20 行输出:", "warn")
            for line in pyi_lines[-20:]:
                print(f"    {line}", flush=True)
            return False

        _log("PyInstaller 打包完成", "ok")
        return True

    except FileNotFoundError:
        _log("PyInstaller 未找到，请先安装: pip install pyinstaller", "error")
        return False


def step_verify():
    """验证构建产物。"""
    _log("验证构建产物 ...", "step")
    exe = DIST_DIR / NAME / f"{NAME}.exe"

    if not exe.exists():
        _log(f"可执行文件不存在: {exe}", "error")
        return False

    size_mb = exe.stat().st_size / (1024 * 1024)
    dir_size = sum(
        f.stat().st_size for f in (DIST_DIR / NAME).rglob("*") if f.is_file()
    ) / (1024 * 1024)

    _log(f"  可执行文件: {exe.name} ({size_mb:.1f} MB)", "info")
    _log(f"  文件夹总大小: {dir_size:.1f} MB", "info")
    _log(f"  输出路径: {exe}", "info")
    _log("验证通过", "ok")
    return True


def step_create_launcher():
    """创建启动说明文件。"""
    launcher = DIST_DIR / NAME / "启动.bat"
    launcher.write_text(
        f'@echo off\n'
        f'start "" "{NAME}.exe" --once\n',
        encoding="utf-8",
    )
    _log(f"  已创建启动脚本: {launcher.name}", "info")


# ══════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════

def main():
    args = sys.argv[1:]
    do_clean = "--clean" in args
    no_console = "--no-console" in args

    print()
    print(f"\033[36m╔{'═' * 58}╗\033[0m")
    print(f"\033[36m║\033[0m  \033[1;37mWARFRAME-RELIC  打包脚本\033[0m" + " " * 32 + "\033[36m║\033[0m")
    print(f"\033[36m║\033[0m  PyInstaller onedir" + " " * 39 + "\033[36m║\033[0m")
    print(f"\033[36m╚{'═' * 58}╝\033[0m")
    print()

    # ── 步骤 1: 检查 PyInstaller ──
    if not step_check_pyinstaller():
        sys.exit(1)

    # ── 步骤 2: 清理 ──
    if do_clean:
        step_clean()
    else:
        _log("跳过清理（使用 --clean 可强制清理）", "info")

    # ── 步骤 3: 打包 ──
    overall_start = time.time()

    if not step_build(no_console=no_console):
        sys.exit(1)

    # ── 步骤 4: 创建启动脚本 ──
    step_create_launcher()

    # ── 步骤 5: 验证 ──
    if not step_verify():
        sys.exit(1)

    # ── 完成 ──
    overall = time.time() - overall_start
    print()
    print(f"\033[32m{'═' * 60}\033[0m")
    print(f"\033[1;32m  打包成功! 耗时 {overall:.1f}s\033[0m")
    print(f"\033[32m  输出: {DIST_DIR / NAME}\033[0m")
    print(f"\033[32m  启动: {DIST_DIR / NAME / f'{NAME}.exe'} --once\033[0m")
    print(f"\033[32m{'═' * 60}\033[0m")
    print()


if __name__ == "__main__":
    main()