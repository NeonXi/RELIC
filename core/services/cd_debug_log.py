"""
[L-Service] core.services.cd_debug_log — CD 辅助调试日志工具

依赖: Python 标准库
禁止: PySide6 (除 Signal)

提供统一的 [CD] 前缀日志,既 print 到 stdout(CMD 可见)
也写到 data/logs/cd_assist_debug.log 文件(便于事后查阅)。

输出格式(4 列对齐,固定宽度,易于扫读):
  [CD] HH:MM:SS.mmm [module] | 符号 LEVEL | message
   │    │            │         │      │       │
   │    │            │         │      │       └─ 消息正文
   │    │            │         │      └─ 级别 (INFO / OK / WARN / ERR),4 字符宽
   │    │            │         └─ 符号 (ℹ ✓ ⚠ ✗),2 字符宽
   │    │            └─ 模块 (hook/service/mgr/ovl/shell),8 字符宽左对齐
   │    └─ 时间戳(毫秒精度)
   └─ 固定标识

级别语义:
  INFO  正常事件/状态变化        ℹ
  OK    成功完成               ✓
  WARN  警告(非致命,但需关注)  ⚠
  ERR   错误(失败/异常)        ✗

颜色 (Windows 10+ ANSI VT 启用时):
  INFO  默认色
  OK    绿色  \\033[92m
  WARN  黄色  \\033[93m
  ERR   红色  \\033[91m
  文件写入: 不带颜色码(纯文本),避免污染日志文件
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from pathlib import Path

# ── 日志文件路径(打包/开发环境自适应,见 core.paths) ──
from core.paths import user_data_dir as _user_data_dir
_LOG_DIR = _user_data_dir() / "logs"
_LOG_FILE = _LOG_DIR / "cd_assist_debug.log"
_LOG_FILE_MAX_BYTES = 1 * 1024 * 1024  # 1MB 轮转

_lock = threading.Lock()
_file_handle = None
_ansi_enabled = None  # 懒检测


# 级别 → (符号, 颜色码)
_LEVEL_DISPLAY = {
    "INFO": ("ℹ ", ""),         # 蓝 info 符号
    "OK":   ("✓ ", "\033[92m"),  # 绿
    "WARN": ("⚠ ", "\033[93m"),  # 黄
    "ERR":  ("✗ ", "\033[91m"),  # 红
}
_RESET = "\033[0m"


def _enable_windows_vt():
    """Windows 10+ 启用 ANSI VT 处理(否则颜色码会显示成乱码)。

    仅在 Windows + Python < 10 时需要(3.10+ 默认启用? 不,3.x 仍要显式启用)。
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        # GetConsoleMode / SetConsoleMode in STD_OUTPUT_HANDLE(-11)
        handle = kernel32.GetStdHandle(-11)
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:
            return True  # 已启用
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _ansi_support() -> bool:
    """检测 ANSI 颜色是否可用(缓存结果)。"""
    global _ansi_enabled
    if _ansi_enabled is None:
        # 非 Windows: 通常支持
        if os.name != "nt":
            _ansi_enabled = True
        else:
            _ansi_enabled = _enable_windows_vt()
    return _ansi_enabled


def _ensure_log_file():
    """确保日志文件可写(惰性初始化 + 简易轮转)。"""
    global _file_handle
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        if _file_handle is None:
            # 如果文件超过 1MB,轮转
            if _LOG_FILE.exists() and _LOG_FILE.stat().st_size > _LOG_FILE_MAX_BYTES:
                backup = _LOG_FILE.with_suffix(".log.old")
                try:
                    if backup.exists():
                        backup.unlink()
                    _LOG_FILE.rename(backup)
                except OSError:
                    pass
            _file_handle = open(_LOG_FILE, "a", encoding="utf-8")
    except Exception:
        _file_handle = None  # 文件打不开就只走 stdout


def log(tag: str, msg: str, level: str = "INFO") -> None:
    """写一条调试日志。

    参数:
      tag:   子模块前缀,如 "hook" / "service" / "view" / "mgr" / "ovl" / "shell"
      msg:   人类可读的消息(可含 ✓ ✗ 符号,但已不必要,改用 level)
      level: 级别 (INFO / OK / WARN / ERR),默认 INFO

    输出格式:
      [CD] HH:MM:SS.mmm [tag     ] | ℹ INFO | msg    (符号 + 4 字符级别)
    """
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # 毫秒
    sym, color = _LEVEL_DISPLAY.get(level.upper(), ("  ", ""))
    level_str = level.upper().ljust(4)
    line = f"[CD] {ts} [{tag:<8}] | {sym} {level_str} | {msg}"
    # 文件版本: 无颜色
    file_line = f"[CD] {ts} [{tag:<8}] | {sym} {level_str} | {msg}"
    # 终端版本: 启用颜色时给 level 部分上色
    if color and _ansi_support():
        # 给 "符号 级别" 字段上色
        head, _, tail = line.partition(f"| {sym} {level_str} |")
        line = f"{head}| {color}{sym} {level_str}{_RESET} | {tail}"

    try:
        print(line, flush=True)
    except Exception:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except Exception:
            pass
    with _lock:
        _ensure_log_file()
        if _file_handle is not None:
            try:
                _file_handle.write(file_line + "\n")
                _file_handle.flush()
            except Exception:
                pass


def log_path() -> Path:
    """返回日志文件路径(便于用户找到)。"""
    return _LOG_FILE
