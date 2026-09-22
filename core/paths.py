"""
[L-Infrastructure] core.paths — 运行环境路径解析(纯 Python,无 Qt)

依赖: Python 标准库
禁止: PySide6 / QtWidgets / QtCore / QtGui

职责:
    统一「打包(PyInstaller onedir)」与「开发」两种环境的路径解析,
    替代散落各模块的 ``Path(__file__).parent.parent.parent`` 推导。

    ┌─────────────┬────────────────────────┬────────────────────────┐
    │ 环境        │ 开发                    │ 打包(onedir)           │
    ├─────────────┼────────────────────────┼────────────────────────┤
    │ app_root    │ 项目根                  │ exe 所在目录            │
    │ resource_dir│ 项目根/data(只读约定)  │ _internal/data(随包)   │
    │ user_data_dir│ 项目根/data           │ exe旁/data(降级APPDATA)│
    └─────────────┴────────────────────────┴────────────────────────┘

使用规则(写入路径迁移必读):
  - **只读资源**(tokens yaml/字体/OCR模型/图标/初始模板):
    ``resource_dir()`` —— 随包分发,运行期绝不写入
  - **用户数据**(配置 json/数据库/缓存/日志/背景图):
    ``user_data_dir()`` —— 运行期读写;exe 旁不可写时自动降级
    ``%LOCALAPPDATA%\\WARFRAME-RELIC\\data`` 并打印警告
  - **首启模板复制**: ``ensure_user_file("warframe.db")`` ——
    用户数据不存在时从只读资源复制初始模板;已存在则不动(保住用户修改)

开发环境行为完全等价于旧路径推导(项目根/data),迁移零行为变化。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# ── 模块级缓存(探测只做一次,避免每次调用都做 IO) ──
_user_data_cache: Path | None = None


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境。"""
    return getattr(sys, "frozen", False)


def app_root() -> Path:
    """应用根目录(用户数据/external 等可写内容的根)。

    - 开发: 项目根(core/ 的上一级)
    - 打包: exe 所在目录(onedir 主目录)
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """只读资源目录(随包分发,运行期绝不写入)。

    - 开发: 项目根/data
    - 打包: _internal/data(PyInstaller datas 把 data/ 放到 MEIPASS 下)
    """
    if is_frozen():
        # onedir 模式: sys._MEIPASS == <exe目录>/_internal
        return Path(sys._MEIPASS) / "data"  # noqa: SLF001
    return Path(__file__).resolve().parent.parent / "data"


def resource_root() -> Path:
    """只读资源根目录(assets 等非 data 资源的定位基准)。

    - 开发: 项目根
    - 打包: _internal(PyInstaller 解包根,assets 位于其下)
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent.parent


def _ensure_writable(d: Path) -> bool:
    """探测目录可写(不存在则尝试创建),成功返回 True。"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_probe"
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


def user_data_dir() -> Path:
    """用户数据目录(运行期读写:配置/数据库/缓存/日志/背景图)。

    优先 exe 旁 data/(绿色软件,用户可整目录拷走);
    不可写(如 Program Files 权限)自动降级 %LOCALAPPDATA%/WARFRAME-RELIC/data,
    并打印警告说明降级位置(方便用户找回数据)。结果模块级缓存。
    """
    global _user_data_cache
    if _user_data_cache is not None:
        return _user_data_cache

    primary = app_root() / "data"
    if _ensure_writable(primary):
        _user_data_cache = primary
        return primary

    fallback = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        / "WARFRAME-RELIC"
        / "data"
    )
    _ensure_writable(fallback)
    print(
        f"[paths] 警告: {primary} 不可写,用户数据降级到 {fallback}",
        flush=True,
    )
    _user_data_cache = fallback
    return fallback


def ensure_user_file(name: str) -> Path:
    """确保用户数据文件存在:不存在则从只读资源复制初始模板。

    首启迁移策略(同时解决"升级丢配置"):
      - user_data/<name> 已存在 → 原样返回(用户修改永不被覆盖)
      - 不存在且 resource_dir()/data/<name> 存在 → 复制模板再返回
      - 两者都无 → 返回 user_data 路径(由调用方自行生成默认内容)

    Args:
        name: 文件名(如 "warframe.db" / "pixel_font.json")

    Returns:
        user_data_dir() / name
    """
    target = user_data_dir() / name
    if target.exists():
        return target
    template = resource_dir() / name
    if template.exists():
        try:
            shutil.copy2(template, target)
        except OSError as e:
            print(f"[paths] 警告: 模板复制失败 {template} -> {target}: {e}", flush=True)
    return target
