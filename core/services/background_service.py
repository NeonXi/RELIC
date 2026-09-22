"""
[L-Service] BackgroundService — 自定义窗口背景图 业务逻辑

依赖: Python 标准库(pathlib/shutil/time) + PySide6.QtCore(QObject/Signal/QTimer)
禁止: PySide6.QtWidgets / QtGui、直接操作 widget(只持有 layer 引用并调其接口)
职责:
  - 背景原图的导入(复制进 data/backgrounds/)、更换、清除(删除旧文件)
  - 记录用户裁剪选区（crop；None=整图）
  - 维护图片透明度(0-100)、模糊强度(0-100)
  - 全局沉浸模式（开关 + 沉浸强度节流）：开启后导航栏/卡片透出壁纸
  - 对滑块高频输入做固定频率节流(leading + 60ms tick)
  - 配置持久化(经 core.services.ui_prefs 读写 ui_prefs.json)

背景层自适应：保存的是「原图 + 选区」，窗口改变宽高比时由
CyberBackgroundLayer 在原图内围绕选区重新取画面，选区主体不丢失。

设计参考: CdAssistService 的"service 持有 view、反向调用"模式，
layer(widget)不反向依赖本服务，符合分层铁律。

错误处理: 文件复制/删除/配置读写全部 try/except，失败只记日志，
绝不向 UI 抛异常。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

# ── 常量 ──

# data/backgrounds/ 背景原图存放目录(打包/开发环境自适应,见 core.paths)
from core.paths import user_data_dir as _user_data_dir
_BG_DIR = _user_data_dir() / "backgrounds"

# 允许导入的图片格式
ALLOWED_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

# 滑块节流：拖动期间每 60ms 最多向 layer 推一次（首次立即响应）
THROTTLE_MS: int = 60


class BackgroundService(QObject):
    """背景图服务（单例）。

    Signals:
        background_changed(source, crop, opacity, blur):
            背景配置变化（供设置页同步控件状态用；layer 由本服务直接驱动）
            source 为原图文件名(str)，crop 为 [x,y,w,h] 或 None
        immersive_changed(enabled, strength, color_mode):
            全局沉浸模式变化（样式控制器据此切换控件层全局状态/底色 QSS;
            color_mode 随信号携带("theme"/"black"),订阅方无需反向拉单例）
    """

    background_changed = Signal(str, object, int, int)
    immersive_changed = Signal(bool, int, str)
    immersive_color_changed = Signal(str)

    _instance: "BackgroundService | None" = None

    @classmethod
    def instance(cls) -> "BackgroundService":
        """单例访问（惰性创建）。"""
        if cls._instance is None:
            cls._instance = BackgroundService()
        return cls._instance

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # 当前原图文件名(data/backgrounds/ 下；空串=未设置)
        self._source: str = ""
        # 用户裁剪选区（原图坐标 x,y,w,h）；None = 使用整图
        self._crop: list | None = None
        # 图片不透明度 / 模糊强度（0-100）
        self._opacity: int = 100
        self._blur: int = 0
        # 全局沉浸模式 / 沉浸强度（0-100，越大越透）
        self._immersive: bool = False
        self._immersive_strength: int = 70
        # 沉浸底色预设 "theme"=沿用 token 当前主题底色 / "black"=纯黑
        self._immersive_color: str = "theme"

        # layer（BackgroundLayer）引用，由 AppShell 注入；None 时只维护状态
        self._layer = None

        # ── 节流器（opacity / blur / immersive_strength：timer + 待提交值）──
        self._throttles: dict[str, dict] = {}
        for name in ("opacity", "blur", "immersive_strength"):
            timer = QTimer(self)
            timer.setInterval(THROTTLE_MS)
            timer.setSingleShot(False)
            timer.timeout.connect(lambda n=name: self._on_throttle_tick(n))
            self._throttles[name] = {"timer": timer, "pending": None}

    # ════════════════════════════════════
    #  生命周期
    # ════════════════════════════════════

    def load_on_start(self) -> None:
        """应用启动时调用：从 ui_prefs.json 恢复背景配置并应用到 layer。

        配置指向的原图若已不存在（被手动删除），按"未设置"处理，
        并顺手清空配置里的路径。
        """
        try:
            from core.services.ui_prefs import load_background_prefs
            prefs = load_background_prefs()
        except Exception:
            return

        source = prefs.get("source", "")
        crop = prefs.get("crop")
        opacity = prefs.get("opacity", 100)
        blur = prefs.get("blur", 0)
        immersive = prefs.get("immersive", False)
        strength = prefs.get("immersive_strength", 70)
        immersive_color = prefs.get("immersive_color", "theme")

        if source and not self._bg_dir_path(source).exists():
            # 文件丢失：丢弃无效配置（保留数值默认）
            self._source = ""
            self._crop = None
            self._opacity = opacity
            self._blur = blur
            self._immersive = immersive
            self._immersive_strength = strength
            self._immersive_color = (
                immersive_color if immersive_color in ("theme", "black") else "theme"
            )
            self._persist()
            self.immersive_changed.emit(
                self._immersive, self._immersive_strength, self._immersive_color
            )
            self.immersive_color_changed.emit(self._immersive_color)
            return

        self._source = source
        self._crop = crop
        self._opacity = opacity
        self._blur = blur
        self._immersive = immersive
        self._immersive_strength = strength
        self._immersive_color = (
            immersive_color if immersive_color in ("theme", "black") else "theme"
        )
        self._apply_to_layer()
        # 通知样式控制器应用沉浸全局状态（标志/底色 QSS/重绘）
        self.immersive_changed.emit(
            self._immersive, self._immersive_strength, self._immersive_color
        )
        self.immersive_color_changed.emit(self._immersive_color)

    # ════════════════════════════════════
    #  图片管理
    # ════════════════════════════════════

    def import_image(self, src_path: str, crop: list | None) -> bool:
        """导入新背景原图：复制进 data/backgrounds/，成功后删除旧文件。

        Args:
            src_path: 用户通过文件对话框选中的原图绝对路径
            crop: 用户裁剪选区 [x,y,w,h]（原图坐标）；None=整图

        Returns:
            True = 复制成功并已生效；False = 文件无效/格式不支持/复制失败
        """
        src = Path(src_path)
        if not src.is_file():
            return False
        suffix = src.suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            return False

        # 规整 crop（必须是 4 元素且范围合法；非法一律按整图）
        clean_crop = self._sanitize_crop(crop)

        try:
            _BG_DIR.mkdir(parents=True, exist_ok=True)
            # 时间戳文件名，避免重名
            new_name = f"src_{int(time.time() * 1000)}{suffix}"
            dst = _BG_DIR / new_name
            shutil.copy2(src, dst)
        except Exception as e:
            print(f"[BackgroundService] 背景原图复制失败: {e}", flush=True)
            return False

        old_name = self._source
        self._source = new_name
        self._crop = clean_crop
        # 新图就位后再删旧图（防止复制失败导致无背景）
        if old_name and old_name != new_name:
            self._delete_file(old_name)

        self._apply_to_layer()
        self._persist()
        return True

    def clear_background(self) -> None:
        """清除背景图：删除原图文件，恢复纯主题背景。"""
        old_name = self._source
        self._source = ""
        self._crop = None
        if old_name:
            self._delete_file(old_name)
        self._apply_to_layer()
        self._persist()

    # ════════════════════════════════════
    #  参数调节（节流）
    # ════════════════════════════════════

    def request_opacity(self, value: int) -> None:
        """透明度滑块输入（高频）：节流后应用。"""
        self._request("opacity", int(value))

    def request_blur(self, value: int) -> None:
        """模糊度滑块输入（高频）：节流后应用。"""
        self._request("blur", int(value))

    def set_immersive(self, enabled: bool) -> None:
        """沉浸模式开关（低频）：更新状态、通知外壳、落盘。"""
        enabled = bool(enabled)
        if enabled == self._immersive:
            return
        self._immersive = enabled
        self.immersive_changed.emit(
            enabled, self._immersive_strength, self._immersive_color
        )
        self._persist()

    def set_immersive_color(self, mode: str) -> None:
        """沉浸底色预设切换（低频）：更新状态、通知外壳、落盘。

        Args:
            mode: "theme"=沿用 token 当前主题底色 / "black"=纯黑
        """
        if mode not in ("theme", "black"):
            mode = "theme"
        if mode == self._immersive_color:
            return
        self._immersive_color = mode
        self.immersive_color_changed.emit(mode)
        self._persist()

    def request_immersive_strength(self, value: int) -> None:
        """沉浸强度滑块输入（高频）：节流后通知外壳应用。"""
        self._request("immersive_strength", int(value))

    def commit(self) -> None:
        """滑块释放时调用：立即落盘当前配置（拖动过程中不写文件）。"""
        self._persist()

    def _request(self, name: str, value: int) -> None:
        """通用节流入口：首次立即应用，之后固定频率合并最新值。"""
        value = max(0, min(100, value))
        entry = self._throttles[name]
        timer: QTimer = entry["timer"]

        if not timer.isActive():
            # leading edge：立即响应，启动节流窗口
            setattr(self, f"_{name}", value)
            if name == "immersive_strength":
                self.immersive_changed.emit(
                    self._immersive, self._immersive_strength,
                    self._immersive_color,
                )
            else:
                self._apply_to_layer()
            timer.start()
        else:
            # 窗口内：只记最新值，tick 时合并
            entry["pending"] = value

    def _on_throttle_tick(self, name: str) -> None:
        """节流窗口 tick：有待提交值则应用并落盘，否则关闭窗口。"""
        entry = self._throttles[name]
        pending = entry["pending"]
        if pending is None:
            entry["timer"].stop()
            return
        entry["pending"] = None
        setattr(self, f"_{name}", pending)
        if name == "immersive_strength":
            self.immersive_changed.emit(
                self._immersive, self._immersive_strength,
                self._immersive_color,
            )
        else:
            self._apply_to_layer()
        # 即时落盘：防止用户拖动后未正常释放(直接切页面/关窗)导致设置丢失。
        # 写小 JSON <1ms，60ms 一次的频率无性能压力。
        self._persist()

    # ════════════════════════════════════
    #  状态查询（供设置页初始化）
    # ════════════════════════════════════

    def get_state(self) -> dict:
        """返回当前完整状态 {source, crop, opacity, blur, immersive,
        immersive_strength, immersive_color}。"""
        return {
            "source": self._source,
            "crop": self._crop,
            "opacity": self._opacity,
            "blur": self._blur,
            "immersive": self._immersive,
            "immersive_strength": self._immersive_strength,
            "immersive_color": self._immersive_color,
        }

    @property
    def source(self) -> str:
        return self._source

    @property
    def crop(self) -> list | None:
        return list(self._crop) if self._crop is not None else None

    @property
    def opacity(self) -> int:
        return self._opacity

    @property
    def blur(self) -> int:
        return self._blur

    @property
    def immersive(self) -> bool:
        return self._immersive

    @property
    def immersive_strength(self) -> int:
        return self._immersive_strength

    @property
    def immersive_color(self) -> str:
        return self._immersive_color

    # ════════════════════════════════════
    #  layer 注入（AppShell 调用）
    # ════════════════════════════════════

    def set_layer(self, layer) -> None:
        """注入背景层并立即把当前状态同步给它。"""
        self._layer = layer
        self._apply_to_layer()

    # ════════════════════════════════════
    #  内部
    # ════════════════════════════════════

    @staticmethod
    def _bg_dir_path(filename: str) -> Path:
        return _BG_DIR / filename

    @staticmethod
    def _sanitize_crop(crop) -> list | None:
        """裁剪选区合法性检查。非法/越界返回 None（按整图处理）。

        注意：无法在此获知原图实际尺寸（未加载图片），只做结构检查；
        最终越界由 BackgroundLayer 取画面时自然钳制。
        """
        if not isinstance(crop, (list, tuple)) or len(crop) != 4:
            return None
        try:
            vals = [int(v) for v in crop]
        except (TypeError, ValueError):
            return None
        if vals[0] < 0 or vals[1] < 0 or vals[2] <= 0 or vals[3] <= 0:
            return None
        return vals

    def _delete_file(self, filename: str) -> None:
        """删除背景原图文件（失败只记日志）。

        shutil.copy2 会保留源文件属性；源文件若为只读，副本也只读，
        直接 unlink 会 PermissionError，故先补一个所有者写权限。
        """
        try:
            p = _BG_DIR / filename
            if p.is_file():
                try:
                    p.chmod(p.stat().st_mode | 0o200)
                except OSError:
                    pass
                p.unlink()
        except Exception as e:
            print(f"[BackgroundService] 旧背景图删除失败 {filename}: {e}", flush=True)

    def _apply_to_layer(self) -> None:
        """把当前配置推给背景层（无 layer 时跳过），并广播变化。"""
        if self._layer is not None:
            try:
                path = (_BG_DIR / self._source) if self._source else None
                self._layer.apply_background(
                    path, self._crop, self._opacity, self._blur
                )
            except Exception as e:
                print(f"[BackgroundService] 应用到背景层失败: {e}", flush=True)
        self.background_changed.emit(
            self._source, list(self._crop) if self._crop else None,
            self._opacity, self._blur,
        )

    def _persist(self) -> None:
        """落盘当前配置（失败只记日志）。"""
        try:
            from core.services.ui_prefs import save_background_prefs
            save_background_prefs(
                self._source, self._crop, self._opacity, self._blur,
                self._immersive, self._immersive_strength,
                self._immersive_color,
            )
        except Exception as e:
            print(f"[BackgroundService] 配置保存失败: {e}", flush=True)
