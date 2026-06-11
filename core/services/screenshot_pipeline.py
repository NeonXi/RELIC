"""
[L-Service] 截图OCR管线服务（ScreenshotPipelineService）

从 main.py AppCore 迁移而来，封装完整的：
  快捷键触发 → 截图 → OCR识别 → 显示功能按钮 → 执行功能标注

职责：
  - 管理全局热键注册（HotkeyManager）
  - 管理截图摄像头（dxcam）
  - 管理 Overlay 覆盖层 UI
  - 管理 OCR 识别线程（遗物/物品）
  - 编排功能模式执行（出入库/内容/翻译）

信号:
    log_emitted(str, str): 日志消息 (level, message)
    ready_changed(bool): 组件就绪状态变化
    ocr_finished(str, list): OCR完成 (ocr_type, results)

用法:
    from core.services.screenshot_pipeline import ScreenshotPipelineService
    svc = ScreenshotPipelineService(app)
    svc.start()   # 注册热键、后台加载组件
"""

from __future__ import annotations

import os
import sys
import time
import threading
from typing import Callable, Optional

# ---- 性能优化：限制 ONNX Runtime CPU 线程数 ----
_OCR_THREADS = max(2, min(4, os.cpu_count() // 2 if os.cpu_count() else 4))
os.environ["OMP_NUM_THREADS"] = str(_OCR_THREADS)
os.environ["ORT_NUM_THREADS"] = str(_OCR_THREADS)
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"

import threading
from typing import Callable, Optional

from core.services._event_emitter import EventEmitter
from core.hotkey_config import (
    load_hotkeys, DEFAULT_HOTKEYS,
    load_feature_toggles, FEATURE_TOGGLE_REQUIRES,
)
from core.constants import DXCAM_MAX_RETRIES, DXCAM_RETRY_BASE_SLEEP
from core.hotkey_manager import HotkeyManager
from core.mode_handlers import (
    handle_check_status, handle_query_parts, handle_translate,
)


class _TriggerBridge:
    """键盘热键 → 回调桥接。"""
    def __init__(self):
        self.fired = EventEmitter()


class _OCRWorker:
    """后台线程：执行 OCR 识别，完成后触发回调。"""

    def __init__(self, recognizer, frame):
        self.finished = EventEmitter()
        self._recognizer = recognizer
        self._cancelled = False
        # 深拷贝 frame：dxcam 的 frame 是共享内存，跨线程访问可能在 COM 释放后崩溃
        self._frame = frame.copy() if frame is not None else None

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            k32.SetThreadPriority.restype = ctypes.c_int
            k32.SetThreadPriority(k32.GetCurrentThread(), 0x00004000)
        except Exception:
            pass
        try:
            if self._cancelled:
                self.finished.emit([])
                return
            results = self._recognizer.recognize_all_with_boxes(self._frame)
            if not self._cancelled:
                self.finished.emit(results)
        except Exception as e:
            print(f"[Pipeline-OCR] 异常: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.finished.emit([])


class ScreenshotPipelineService:
    """截图OCR管线服务 —— 协调快捷键/截图/OCR/标注全链路。

    生命周期:
      1. 构造 → 创建 Overlay + Bridge
      2. start() → 注册热键 + 后台加载重型组件(摄像头/OCR/DB)
      3. 运行中 → 响应热键/框选/按钮点击
      4. shutdown() → 清理所有资源
    """

    def __init__(self, app):
        self._app = app

        # ── 事件 ──
        self.log_emitted = EventEmitter()       # (level, message)
        self.ready_changed = EventEmitter()      # (is_ready)
        self.ocr_finished = EventEmitter()       # (ocr_type, results)

        # ── UI 层 ──
        self._overlay = None
        self._overlay_ready = False

        # ── 信号桥接 ──
        self._bridge = _TriggerBridge()

        # ── 功能开关 ──
        self._feature_toggles: dict[str, bool] = {}

        # ── 核心数据 ──
        self._last_frame = None
        self._last_region = None
        self._last_relics: list = []
        self._last_items: list = []
        self._last_texts: list = []

        # ── OCR 线程管理 ──
        self._ocr_thread: Optional[threading.Thread] = None
        self._ocr_worker: Optional[_OCRWorker] = None
        self._ocr_lock = threading.Lock()
        self._pending_mode: Optional[str] = None

        # ── 重型组件（延迟初始化）──
        self._camera = None
        self._relic_ocr = None
        self._item_ocr = None
        self._relic_db = None

        # ── 就绪标志 ──
        self._ocr_ready = False
        self._camera_ready = False
        self._all_ready = False

        # ── 热键管理器 ──
        self._hotkey_mgr = HotkeyManager(self._bridge, self._log_fn, app)

    # ════════════════════════════════════
    #  生命周期
    # ════════════════════════════════════

    def start(self):
        """启动管线：创建 Overlay（不显示）、注册热键、后台加载组件。

        Overlay 延迟到用户触发截图时才显示（按需显示），避免启动时出现多余窗口。
        """
        from core.overlay import Overlay

        # 创建 Overlay（不立即显示，截图时按需 show + raise_）
        self._overlay = Overlay()
        self._overlay_ready = True

        # 绑定事件
        self._bind_events()

        # 注册热键
        self._hotkey_mgr.register_initial()

        # 注册退出清理
        self._app.aboutToQuit.connect(self.shutdown)

        # 后台加载重型组件
        threading.Timer(0.5, self._lazy_init_background).start()

        self._log("info", "截图管线已启动")

    def shutdown(self):
        """清理所有资源。"""
        self._kill_ocr_thread()
        self._clear_results()

        if self._overlay:
            self._overlay.clear_annotations()
            self._overlay.close()

        if self._relic_db:
            try:
                self._relic_db.close()
            except Exception:
                pass

        self._hotkey_mgr.clear()
        self._camera = None
        print("[Pipeline] 所有运行缓存已清理", flush=True)

    # ════════════════════════════════════
    #  后台初始化
    # ════════════════════════════════════

    def _lazy_init_background(self):
        """后台线程静默加载重型组件。"""
        def _load():
            try:
                # 1. 摄像头
                self._log("info", "正在初始化摄像头 (dxcam)...")
                self._camera = self._create_camera_with_retry()
                self._camera_ready = True
                self._log("ok", "摄像头初始化完成")

                # 2. 遗物 OCR
                self._log("info", "正在加载遗物 OCR 模型...")
                from core.recognizers.relic_name import RelicNameRecognizer
                self._relic_ocr = RelicNameRecognizer()

                # 3. 物品 OCR
                self._log("info", "正在加载物品 OCR 模型...")
                from core.recognizers.item_name import ItemNameRecognizer
                self._item_ocr = ItemNameRecognizer()
                self._ocr_ready = True
                self._log("ok", "OCR 引擎初始化完成 (遗物 + 物品)")

                # 4. 遗物数据库
                self._log("info", "正在加载数据库...")
                from data.wfinfo_relics import RelicDB
                self._relic_db = RelicDB()
                if not self._relic_db.load():
                    self._log("warn", "数据库未加载，请在数据总览页面更新数据")
                else:
                    stats = self._relic_db.stats()
                    self._log("ok",
                              f"数据库已就绪 -- {stats['total_relics']} 个遗物 | "
                              f"出库 {stats['available']} | 入库 {stats['vaulted']}")

                # 功能开关
                self._feature_toggles = load_feature_toggles()

                # 全部就绪
                self._all_ready = True
                self.ready_changed.emit(True)
                self._log("ok", "=== 截图管线所有组件加载完成 ===")

            except Exception as e:
                self._log("error", f"后台组件初始化失败: {e}")
                import traceback
                traceback.print_exc()

        t = threading.Thread(target=_load, daemon=True, name="PipelineLazyInit")
        t.start()

    @staticmethod
    def _create_camera_with_retry(max_retries=DXCAM_MAX_RETRIES):
        """带重试的 dxcam 摄像头创建。"""
        import dxcam
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                return dxcam.create(output_idx=0, output_color="BGR")
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    wait = DXCAM_RETRY_BASE_SLEEP * attempt
                    print(f"[Pipeline-摄像头] 初始化失败 (第{attempt}/{max_retries}): {e}",
                          flush=True)
                    time.sleep(wait)
        raise RuntimeError(f"无法初始化 dxcam 摄像头（已重试 {max_retries} 次）: {last_err}")

    # ════════════════════════════════════
    #  事件绑定
    # ════════════════════════════════════

    def _bind_events(self):
        if self._overlay:
            self._overlay.on_selection_done = self._on_selection_done
            self._overlay.mode_selected.connect(self._on_mode_selected)
        self._bridge.fired.connect(self._on_hotkey)

    # ════════════════════════════════════
    #  日志
    # ════════════════════════════════════

    def _log_fn(self, msg: str, log_type: str = "info", source: str = ""):
        """HotkeyManager 兼容的日志回调。"""
        self._log(log_type, msg)

    def _log(self, level: str, msg: str, source: str = ""):
        prefix = {"info": " ", "warn": "[!]", "error": "[x]", "ok": "[ok]"}.get(level, " ")
        src = f"[{source}] " if source else ""
        print(f"[Pipeline] [{time.strftime('%H:%M:%S')}] {src}{prefix} {msg}", flush=True)
        self.log_emitted.emit(level, msg)

    # ════════════════════════════════════
    #  热键入口
    # ════════════════════════════════════

    def _on_hotkey(self, action: str):
        """所有快捷键统一入口（防重入 + 就绪守卫）。"""
        now = time.time()
        if now - self._hotkey_mgr.last_action_time < 0.5:
            return
        self._hotkey_mgr.last_action_time = now

        if not self._camera_ready:
            self._log("warn", "摄像头正在初始化，请稍候...", source="_on_hotkey")
            return
        if action in ('select', 'fullscreen') and not self._ocr_ready:
            self._log("warn", "OCR 引擎正在初始化，请稍候...", source="_on_hotkey")
            return

        self._log("info", f"触发: {action}", source="_on_hotkey")

        if action == 'select':
            self._overlay.start_selection()
        elif action == 'fullscreen':
            self._kill_ocr_thread()
            self._clear_results()
            self._overlay.clear_annotations()
            self._overlay._hide_mode_buttons()
            self._overlay.label.clear()
            self._do_fullscreen_screenshot()

    # ════════════════════════════════════
    #  框选截图
    # ════════════════════════════════════

    def _on_selection_done(self):
        """框选完成回调。"""
        if not self._camera_ready or self._camera is None:
            self._overlay.display("摄像头正在初始化，请稍候...", auto_hide_ms=2000)
            return

        self._kill_ocr_thread()
        self._clear_results()
        self._overlay.clear_annotations()
        self._overlay._hide_mode_buttons()
        self._overlay.label.clear()

        region_info = self._overlay._region_selector.last_region
        if region_info is None:
            from data.ui_strings import S
            self._overlay.display(S("overlay", "please_select_first"), auto_hide_ms=3000)
            return

        logical = region_info['logical']
        phys = region_info['physical']
        frame = self._camera.grab(region=phys)
        if frame is None:
            from data.ui_strings import S
            self._overlay.display(S("overlay", "screenshot_failed"), auto_hide_ms=3000)
            return

        self._after_screenshot(frame, logical)

    # ════════════════════════════════════
    #  全屏截图
    # ════════════════════════════════════

    def _do_fullscreen_screenshot(self):
        """区域截图：固定范围 (0,0)-(1300,1080)。"""
        if not self._camera_ready or self._camera is None:
            self._overlay.display("摄像头正在初始化，请稍候...", auto_hide_ms=2000)
            return

        if self._overlay.is_showing_content():
            self._overlay.clear_annotations()
            self._overlay._hide_mode_buttons()
            self._overlay.label.clear()

        self._log("info", "区域截图 -- 开始识别", source="fullscreen")

        dpi = self._overlay._dpi_scale
        # 固定截图区域: 左上角 (0,0)，宽 1300，高 1080（物理像素）
        region_w = 1300
        region_h = 1080
        phys = (0, 0, region_w, region_h)
        logical = (0, 0, int(region_w / dpi), int(region_h / dpi))

        frame = self._camera.grab(region=phys)
        if frame is None:
            from data.ui_strings import S
            self._overlay.display(S("overlay", "fullscreen_failed"), auto_hide_ms=3000)
            return

        from data.ui_strings import S
        self._overlay.display(
            S.format("overlay", "fullscreen_info",
                     w=region_w, h=region_h),
            auto_hide_ms=2000)
        # 确保 overlay 在最前并处于活动状态
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()
        self._after_screenshot(frame, logical)

    # ════════════════════════════════════
    #  截图后处理
    # ════════════════════════════════════

    def _after_screenshot(self, frame, region):
        """截图成功后的统一处理：保存帧 + 显示功能按钮 + 预启动OCR。"""
        # 立即深拷贝：dxcam 帧是共享内存引用，必须在此处复制以确保安全
        self._last_frame = frame.copy() if frame is not None else None
        self._last_region = region
        self._last_relics = []
        self._last_items = []
        self._last_texts = []

        # 只保留 MODE_DEFS 中定义的有效模式，过滤掉未知/已废弃的键
        valid_modes = set(self._overlay.MODE_DEFS.keys()) if hasattr(self._overlay, 'MODE_DEFS') else {
            "check_status", "query_parts", "translate"
        }
        enabled_modes = [
            k for k, v in self._feature_toggles.items()
            if v and k in valid_modes
        ]

        if enabled_modes:
            try:
                self._overlay.show_mode_buttons(enabled_modes)
                self._start_eager_ocr(enabled_modes)
            except Exception as e:
                self._log("error", f"截图后处理异常: {e}")
                import traceback
                traceback.print_exc()
        else:
            from data.ui_strings import S
            self._overlay.display(S("overlay", "screenshot_done"), auto_hide_ms=3000)

    def _start_eager_ocr(self, enabled_modes: list[str]):
        """截图后立即启动 OCR，让用户点击按钮时结果已就绪。"""
        import re
        relic_modes = [m for m in enabled_modes if re.match(r'check_status|query_parts', m)]
        item_modes = [m for m in enabled_modes if re.match(r'translate', m)]

        if relic_modes:
            self._start_ocr('relic', lambda results: None)
        elif item_modes:
            self._start_ocr('item', lambda results: None)

    # ════════════════════════════════════
    #  OCR 线程管理
    # ════════════════════════════════════

    def _start_ocr(self, ocr_type: str, callback: Callable):
        """启动 OCR 识别线程。

        Args:
            ocr_type: 'relic' | 'item'
            callback: 完成回调 (results: list) -> None
        """
        if not self._ocr_ready:
            self._log("warn", "OCR 引擎正在初始化，请稍候...", source="_start_ocr")
            return

        if self._ocr_thread is not None and self._ocr_thread.is_alive():
            self._log("warn", f"OCR 线程忙，跳过 {ocr_type}", source="_start_ocr")
            return

        recognizer_map = {
            'relic': self._relic_ocr,
            'item': self._item_ocr,
        }
        recognizer = recognizer_map.get(ocr_type)
        if not recognizer:
            self._log("error", f"未知 OCR 类型: {ocr_type}", source="_start_ocr")
            return

        self._log("info", f"启动 OCR: {ocr_type}", source="_start_ocr")

        def _delayed_ocr():
            if self._ocr_thread is not None and self._ocr_thread.is_alive():
                return
            self._ocr_worker = _OCRWorker(recognizer, self._last_frame)
            self._ocr_worker.finished.connect(
                lambda results: self._on_ocr_done(results, ocr_type, callback))
            self._ocr_thread = threading.Thread(
                target=self._ocr_worker.run, daemon=True, name=f"OCR-{ocr_type}")
            self._ocr_thread.start()

        threading.Timer(0.08, _delayed_ocr).start()

    def _on_thread_finished(self):
        """OCR 线程结束清理。"""
        with self._ocr_lock:
            self._ocr_thread = None
            self._ocr_worker = None

    def _on_ocr_done(self, results: list, ocr_type: str, callback: Callable):
        """OCR 完成回调。"""
        try:
            if self._last_frame is None:
                return

            if ocr_type == 'relic':
                self._last_relics = results
                if results:
                    names = ' | '.join(n for n, _ in results[:8])
                    self._log("info", f"[遗物识别] {len(results)} 个: {names}",
                              source="_on_ocr_done")
                else:
                    self._log("info", "[遗物识别] 未找到候选", source="_on_ocr_done")
            elif ocr_type == 'item':
                self._last_items = results
                if results:
                    names = ' | '.join(t[0] for t in results[:8])
                    self._log("info", f"[物品识别] {len(results)} 个: {names}",
                              source="_on_ocr_done")
                else:
                    self._log("info", "[物品识别] 未找到候选", source="_on_ocr_done")

            self.ocr_finished.emit(ocr_type, results)
            callback(results)

            # pending_mode: 用户在 OCR 运行时点了按钮
            pending = self._pending_mode
            if pending:
                self._pending_mode = None
                self._execute_mode(pending)

        except Exception as e:
            self._log("error", f"OCR 回调异常: {e}", source="_on_ocr_done")
            import traceback
            traceback.print_exc()

    def _kill_ocr_thread(self):
        """终止当前 OCR 线程。"""
        with self._ocr_lock:
            thread = self._ocr_thread
            worker = self._ocr_worker
            self._ocr_thread = None
            self._ocr_worker = None

        # 通知 worker 取消
        if worker is not None:
            worker.cancel()

        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _clear_results(self):
        """清空缓存结果。"""
        self._last_frame = None
        self._last_region = None
        self._last_relics = []
        self._last_items = []
        self._last_texts = []

    # ════════════════════════════════════
    #  功能模式处理
    # ════════════════════════════════════

    def _on_mode_selected(self, mode: str):
        """用户点击功能按钮。"""
        ocr_type = FEATURE_TOGGLE_REQUIRES.get(mode)

        if self._last_frame is None:
            from data.ui_strings import S
            self._overlay.display(S("overlay", "please_screenshot_first"), auto_hide_ms=3000)
            return

        # 已有 OCR 结果 → 直接执行
        cache_map = {'relic': self._last_relics, 'item': self._last_items, 'text': self._last_texts}
        cached = cache_map.get(ocr_type, [])
        if cached:
            self._execute_mode(mode)
            return

        # OCR 正在运行 → 存储 pending mode
        if self._ocr_thread is not None and self._ocr_thread.is_alive():
            self._pending_mode = mode
            from data.ui_strings import S
            self._overlay.display(S("overlay", "ocr_recognizing"), auto_hide_ms=5000)
            return

        # 需要 OCR
        from data.ui_strings import S
        self._overlay.display(S("overlay", "ocr_recognizing"), auto_hide_ms=5000)

        def _callback(results):
            if not results:
                no_result_msgs = {
                    'relic': "no_relics_detected",
                    'item': "no_items_detected",
                    'text': "no_text_detected",
                }
                msg_key = no_result_msgs.get(ocr_type, "no_items_detected")
                self._overlay.display(S("overlay", msg_key), auto_hide_ms=3000)
                return
            self._execute_mode(mode)

        self._start_ocr(ocr_type, _callback)

    def _execute_mode(self, mode: str):
        """分发到对应的功能处理器。"""
        dpi = self._overlay._dpi_scale
        region = self._last_region
        overlay = self._overlay

        # 需要数据库的功能，在数据库未就绪时提示用户
        if mode in ("check_status", "query_parts") and self._relic_db is None:
            self._log("warn", "数据库未就绪，无法执行查询功能", source="_execute_mode")
            overlay.display(S("overlay", "db_not_ready"), auto_hide_ms=4000)
            return

        if mode == "check_status":
            self._log("info", "出入库查询 -- 开始标注", source="handle_check_status")
            handle_check_status(self._last_relics, self._relic_db, region, dpi, overlay)

        elif mode == "query_parts":
            self._log("info", "遗物内容查询 -- 开始匹配", source="handle_query_parts")
            matched, total, unmatched_names = handle_query_parts(
                self._last_relics, self._relic_db, region, dpi, overlay)
            self._log("info", f"匹配: {matched}/{total}", source="handle_query_parts")
            if unmatched_names:
                self._log("warn", f"未匹配: {', '.join(unmatched_names)}",
                          source="handle_query_parts")

        elif mode == "translate":
            self._log("info", "翻译 -- 开始处理", source="handle_translate")
            result = handle_translate(self._last_items, region, dpi, overlay)
            if result:
                total, matched = result
                self._log("info", f"翻译: {total}个候选 | 匹配 {matched}个",
                          source="handle_translate")

        else:
            self._log("warn", f"未知模式: {mode}", source="_execute_mode")

    # ════════════════════════════════════
    #  公开接口
    # ════════════════════════════════════

    @property
    def overlay(self):
        """获取 Overlay 实例（用于外部控制）。"""
        return self._overlay

    @property
    def hotkey_manager(self):
        """获取 HotkeyManager 实例（用于配置页）。"""
        return self._hotkey_mgr

    @property
    def is_ready(self) -> bool:
        """是否所有组件都已就绪。"""
        return self._all_ready

    def update_feature_toggles(self, toggles: dict):
        """更新功能开关配置（由 TogglesPage 调用）。"""
        self._feature_toggles = toggles
        self._log("info", f"功能开关已更新: {toggles}", source="update_toggles")

    def reregister_hotkeys(self):
        """重新注册热键（保存配置后调用，让修改立即生效）。"""
        from core.hotkey_config import load_hotkeys
        new_hotkeys = load_hotkeys()
        if self._hotkey_mgr:
            self._hotkey_mgr.on_config_changed(new_hotkeys)
            self._log("info", f"热键已重注册: {new_hotkeys}", source="reregister")

    def force_reset_hotkeys(self):
        """紧急重置快捷键。"""
        self._hotkey_mgr.force_reset()

    def reload_db(self):
        """重新加载数据库。"""
        if self._relic_db:
            self._relic_db.invalidate()
            if self._relic_db.load():
                stats = self._relic_db.stats()
                self._log("ok",
                          f"数据库重新加载完成 -- {stats['total_relics']} 个遗物",
                          source="reload_db")
            else:
                self._log("error", "数据库重新加载失败", source="reload_db")
