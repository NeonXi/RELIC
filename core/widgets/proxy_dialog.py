"""
[L5] ProxyDialog — GitHub 代理镜像配置对话框（PySide6 版）。

依赖: PySide6, tokens/, services/config_service.py
职责: 编辑 GitHub 代理镜像列表，测试连通性
复用 core.proxy_config 纯逻辑层。
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QProgressBar, QTextEdit,
)
from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtGui import QColor, QFont

from core.widgets.base import CyberWidgetMixin
from core.widgets.button import CyberButton
from core.proxy_config import (
    get_mirrors, set_mirrors, get_default_mirrors,
    get_config_path, get_repo_defs,
    test_repo_mirror, update_test_result, clear_test_results,
)


class _ProxyTestWorker(QObject):
    """后台线程：并行测试所有代理镜像对所有仓库的连通性。"""

    progress = QtSignal(int, str)       # (pct, 描述)
    log = QtSignal(str, str)            # (level, msg)
    finished = QtSignal(dict)           # 汇总结果
    error = QtSignal(str)               # 错误信息

    def __init__(self, mirrors: list, timeout: int = 10, max_workers: int = 6):
        super().__init__()
        self._mirrors = mirrors
        self._timeout = timeout
        self._max_workers = max_workers
        self._cancelled = False
        self._executor: Optional[ThreadPoolExecutor] = None

    def cancel(self):
        """取消测试。"""
        self._cancelled = True
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def run(self):
        repos = get_repo_defs()
        # 构建任务列表: [(repo_name, mirror_idx, mirror_url), ...]
        tasks = []
        for repo_name in repos:
            for idx, mirror in enumerate(self._mirrors):
                tasks.append((repo_name, idx, mirror))

        total = len(tasks)
        if total == 0:
            self.finished.emit({})
            return

        clear_test_results()
        results = {repo_name: {"working": [], "failed": []} for repo_name in repos}
        completed = 0

        # 并行执行，最多 max_workers 个并发
        self._executor = ThreadPoolExecutor(max_workers=min(self._max_workers, total))
        future_to_task = {}

        for repo_name, idx, mirror in tasks:
            if self._cancelled:
                return
            fut = self._executor.submit(test_repo_mirror, repo_name, mirror, timeout=self._timeout)
            future_to_task[fut] = (repo_name, idx, mirror)

        # 按完成顺序收集结果
        try:
            for future in as_completed(future_to_task):
                if self._cancelled:
                    return

                repo_name, idx, mirror = future_to_task[future]
                completed += 1
                pct = int(completed / total * 100)
                self.progress.emit(pct, f"测试 {repo_name} [{idx + 1}/{len(self._mirrors)}]")
                self.log.emit("info", f"  测试: {repo_name} \u2190 镜像 [{idx}]")

                try:
                    success = future.result()
                except Exception:
                    success = False

                update_test_result(repo_name, idx, success)

                if success:
                    results[repo_name]["working"].append(idx)
                    self.log.emit("ok", f"    [OK] 镜像 [{idx}] 连通")
                else:
                    results[repo_name]["failed"].append(idx)
                    self.log.emit("warn", f"    [X] 镜像 [{idx}] 不可用")

        finally:
            self._executor.shutdown(wait=False)
            self._executor = None

        self.progress.emit(100, "测试完成")
        self.finished.emit(results)


class CyberProxyDialog(QDialog, CyberWidgetMixin):
    """GitHub 代理镜像配置对话框。"""

    # ── token 颜色辅助（带默认值回退）──

    def _tc(self, key: str, default=None) -> QColor:
        """获取 token 颜色，支持默认值回退。"""
        try:
            return self.token_color(key)
        except Exception:
            if default is not None:
                return QColor(default) if not isinstance(default, QColor) else default
            raise

    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        CyberWidgetMixin.__init__(self)

        self.setWindowTitle(self.copy("proxy.window_title", "配置 GitHub 代理镜像"))
        self.setMinimumSize(600, 520)
        self.resize(640, 560)

        bg = self._tc("bg.base")
        border_c = self._tc("alias.border.default")
        text_dim = self._tc("text.disabled")

        self.setStyleSheet(f"""
            QDialog {{
                background-color: rgba({bg.red()},{bg.green()},{bg.blue()}, 250);
            }}
            QLabel {{ color: {text_dim.name()}; background: transparent; }}
        """)

        self._test_worker = None
        self._test_thread = None
        self._build_ui()
        self._load_mirrors()

    # ── UI 构建 ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        accent = self._tc("accent.primary")
        text_dim = self._tc("text.disabled")
        border_c = self._tc("alias.border.default")
        card_bg = self._tc("components.card.bg")
        cyan = self._tc("accent.secondary")
        green = self._tc("alias.semantic.success")
        red = self._tc("alias.semantic.danger")
        orange = self._tc("semantic.warning")

        # 标题
        title = QLabel(self.copy("proxy.title", "GitHub 代理镜像列表"))
        title.setFont(QFont("Iceberg", self.space("font.lg", 14)))
        title.setStyleSheet(f"color: {accent.name()}; background: transparent; border: none;")
        layout.addWidget(title)

        # 说明
        desc = QLabel(self.copy("proxy.desc",
            "每行一个代理镜像 URL 模板。\n"
            "支持占位符: {{owner}}（仓库所有者）、{{repo}}（仓库名）\n"
            "拉取失败时按顺序尝试，连通性测试通过的和上次成功的优先使用。"
        ))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {text_dim.name()}; font-size: {self.space('font.xs', 11)}px; background: transparent; border: none;")
        layout.addWidget(desc)

        # 编辑区
        self._text_edit = QPlainTextEdit()
        text_main = self._tc("text.primary")
        self._text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: rgba({card_bg.red()},{card_bg.green()},{card_bg.blue()}, 200);
                color: {text_main.name()};
                border: 1px solid {border_c.name()};
                border-radius: {self.space('corner.sm', 6)}px;
                font-family: Consolas, Microsoft YaHei, monospace;
                font-size: {self.space('font.sm', 12)}px;
                padding: {self.space('spacing.sm', 8)}px;
            }}
            QScrollBar:vertical {{
                background: rgba({self._tc('bg.raised', QColor(30, 34, 50)).red()},{self._tc('bg.raised', QColor(30, 34, 50)).green()},{self._tc('bg.raised', QColor(30, 34, 50)).blue()}, 180);
                width: {self.space('height.scrollbar', 8)}px; border-radius: {self.space('corner.xs', 4)}px;
            }}
            QScrollBar::handle:vertical {{
                background: {border_c.name()}; border-radius: {self.space('corner.xs', 4)}px; min-height: {self.space('spacing.xxxl', 32)}px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        layout.addWidget(self._text_edit, 1)

        # 配置文件路径提示
        config_path = get_config_path()
        hint = QLabel(
            self.copy("proxy.hint_config",
                "配置文件: {path}\n你也可以直接编辑此文件，修改后无需重启程序即可生效。",
                path=config_path,
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {cyan.name()}; font-size: {self.space('font.micro', 10)}px; background: transparent; border: none;")
        layout.addWidget(hint)

        # 测试进度条
        self._test_progress = QProgressBar()
        self._test_progress.setRange(0, 100)
        self._test_progress.setValue(0)
        self._test_progress.setFixedHeight(18)
        self._test_progress.setFormat("  %p%  %v/%m")
        self._test_progress.hide()
        self._test_progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {border_c.name()}; border-radius: 4px;
                background-color: rgba({card_bg.red()},{card_bg.green()},{card_bg.blue()}, 180);
                text-align: center;
                color: {accent.name()}; font-size: {self.space('font.micro', 10)}px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {cyan.name()}, stop:1 {accent.name()});
                border-radius: {self.space('corner.xs', 4)}px;
            }}
        """)
        layout.addWidget(self._test_progress)

        # 测试日志区
        self._test_log = QTextEdit()
        self._test_log.setReadOnly(True)
        self._test_log.setMaximumHeight(120)
        self._test_log.hide()
        self._test_log.setStyleSheet(f"""
            QTextEdit {{
                background-color: rgba({card_bg.red()},{card_bg.green()},{card_bg.blue()}, 160);
                color: {text_main.name()};
                border: 1px solid {border_c.name()}; border-radius: {self.space('corner.sm', 6)}px;
                font-family: Consolas, monospace;
                font-size: {self.space('font.xs', 11)}px; padding: 8px;
            }}
        """)
        layout.addWidget(self._test_log)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_reset = CyberButton(self.copy("proxy.btn_reset_default", "恢复默认"), variant="ghost")
        self._btn_reset.setToolTip(self.copy("proxy.tip_reset_default", "恢复为程序内置的默认代理镜像列表"))
        self._btn_reset.clicked.connect(self._on_reset_default)
        btn_row.addWidget(self._btn_reset)

        self._btn_test = CyberButton(self.copy("proxy.btn_test", "测试连通性"), variant="solid")
        self._btn_test.setToolTip(self.copy("proxy.tip_test", "测试所有代理镜像对每个仓库的连通性（每项超时 10 秒）"))
        self._btn_test.clicked.connect(self._on_test_connectivity)
        btn_row.addWidget(self._btn_test)

        btn_row.addStretch()

        # 保存 / 取消
        self._btn_save = CyberButton(self.copy("common.save", "保存"), variant="solid")
        self._btn_save.clicked.connect(self._on_accept)
        btn_row.addWidget(self._btn_save)

        self._btn_cancel = CyberButton(self.copy("common.cancel", "取消"), variant="ghost")
        self._btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_cancel)

        layout.addLayout(btn_row)

    # ── 数据加载 / 保存 ──

    def _load_mirrors(self) -> None:
        """加载当前配置到编辑区。"""
        mirrors = get_mirrors()
        self._text_edit.setPlainText("\n".join(mirrors))

    def _on_accept(self) -> None:
        """保存并关闭。"""
        text = self._text_edit.toPlainText().strip()
        mirrors = [line.strip() for line in text.split("\n") if line.strip()]
        if mirrors:
            set_mirrors(mirrors)
        self.accept()

    # ── 操作回调 ──

    def _on_reset_default(self) -> None:
        """恢复默认镜像列表。"""
        defaults = get_default_mirrors()
        self._text_edit.setPlainText("\n".join(defaults))

    def _on_test_connectivity(self) -> None:
        """测试连通性。"""
        text = self._text_edit.toPlainText().strip()
        mirrors = [line.strip() for line in text.split("\n") if line.strip()]
        if not mirrors:
            return
        set_mirrors(mirrors)

        self._test_progress.setValue(0)
        self._test_progress.show()
        self._test_log.clear()
        self._test_log.show()
        self._btn_test.setEnabled(False)
        self._btn_reset.setEnabled(False)

        self._test_worker = _ProxyTestWorker(mirrors, timeout=10)
        self._test_worker.progress.connect(self._on_test_progress)
        self._test_worker.log.connect(self._on_test_log)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.error.connect(self._on_test_error)

        self._test_thread = threading.Thread(target=self._test_worker.run, daemon=True)
        self._test_thread.start()

    def _on_test_progress(self, pct: int, desc: str) -> None:
        self._test_progress.setValue(pct)
        self._test_progress.setFormat(f"  {desc}  %p%")

    def _on_test_log(self, level: str, msg: str) -> None:
        from datetime import datetime
        now = datetime.now().strftime("%H:%M:%S")
        color_map = {
            "ok": self._tc("alias.semantic.success"),
            "warn": self._tc("semantic.warning"),
            "error": self._tc("alias.semantic.danger"),
            "info": self._tc("alias.text.primary"),
        }
        dim = self._tc("text.disabled")
        c = color_map.get(level, self._tc("text.secondary"))
        self._test_log.append(
            f'<span style="color:{dim.name()};">[{now}]</span> '
            f'<span style="color:{c.name()};">{msg}</span>'
        )

    def _on_test_finished(self, results: dict) -> None:
        self._btn_test.setEnabled(True)
        self._btn_reset.setEnabled(True)
        self._test_progress.setFormat(self.copy("proxy.test_complete", "测试完成") + "  %p%")

        yellow = self._tc("accent.primary")
        green = self._tc("alias.semantic.success")
        red = self._tc("alias.semantic.danger")
        dim = self._tc("text.disabled")

        summary_lines = []
        for repo_name in results:
            r = results[repo_name]
            if r["working"]:
                summary_lines.append(
                    f'<span style="color:{green.name()};">'
                    f'[OK] {repo_name}: {len(r["working"])} ' + self.copy("proxy.available_count", "个可用") + '</span>'
                )
            else:
                summary_lines.append(
                    f'<span style="color:{red.name()};">'
                    f'[X] {repo_name}: 0 ' + self.copy("proxy.available_count", "个可用") + '</span>'
                )
        self._test_log.append("")
        self._test_log.append(
            f'<span style="color:{yellow.name()}; font-weight:bold;">'
            f'{" | ".join(summary_lines)}</span>'
        )
        self._test_log.append(
            f'<span style="color:{dim.name()};">'
            + self.copy("proxy.result_saved", "测试结果已保存到 {path}", path=get_config_path()) + '</span>'
        )

    def _on_test_error(self, err_msg: str) -> None:
        self._btn_test.setEnabled(True)
        self._btn_reset.setEnabled(True)
        red = self._tc("alias.semantic.danger")
        self._test_log.append(
            f'<span style="color:{red.name()};">[X] ' + self.copy("proxy.test_error", "测试错误: {err}", err=err_msg) + '</span>'
        )
