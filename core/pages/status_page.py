"""
[L2] StatusPage — 数据总览页面（数据库统计 + 数据管理操作）。

依赖: widgets/, services/
职责: 显示数据库统计信息、数据更新/管理操作
"""
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGridLayout, QFrame,
    QPushButton, QFileDialog, QMessageBox, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer, Signal as QtSignal, QObject
from PySide6.QtGui import QColor, QFont

from core.pages.base_page import PageBase
from core.widgets.card import CyberCard
from core.widgets.button import CyberButton
from core.widgets.log_viewer import CyberLogViewer
from core.tokens.manager import TokenManager


class StatusPage(PageBase):
    page_id = "db_overview"
    page_title = ""  # 由 nav token 动态获取
    page_icon = "nav_status"

    def __init__(self):
        super().__init__()
        self.page_title = self._copy("nav.status", "数据总览")
        # core/pages/ → core/ → 项目根 → data/
        self._data_dir = Path(__file__).resolve().parent.parent.parent / 'data'
        self._db_path = str(self._data_dir / 'warframe.db')
        self._updating = False  # 更新进行中标志
        self._pipeline_bridge = None  # 流水线信号桥接（防止 GC）

    # ── 生命周期 ──

    def on_enter(self) -> None:
        """页面进入时刷新数据。"""
        super().on_enter()
        self._refresh_all_stats()

    def build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)

        # ── 标题 ──
        title = QLabel(self._copy("status.title", "数据库概览"))
        title.setFont(QFont("Iceberg", self._font_size("lg_xl", 18)))
        accent = self._color("accent.primary")
        title.setStyleSheet(f"color: {accent}; padding: 4px 0; background: transparent; border: none;")
        layout.addWidget(title)

        # ── 数据库状态卡片 ──
        status_card = self._build_status_card()
        layout.addWidget(status_card)

        # ── 统计卡片网格 ──
        stats_container = QWidget()
        stats_layout = QGridLayout(stats_container)
        stats_layout.setSpacing(12)

        self._stat_labels = {}

        stats_config = [
            ("relics_total", self._copy("status.stat_relics", "遗物总数"), "0", self._color("accent.primary")),
            ("items_total", self._copy("status.stat_items", "物品总数"), "0", self._color("accent.secondary")),
            ("translations", self._copy("status.stat_translations", "翻译条目"), "0", self._color("brand.green")),
            ("relic_rewards", self._copy("status.stat_rewards", "奖励部件"), "0", self._color("semantic.warning")),
            ("vaulted", self._copy("status.stat_vaulted", "入库"), "0", self._color("brand.magenta")),
            ("available", self._copy("status.stat_available", "出库"), "0", self._color("brand.green")),
        ]

        for i, (key, label, default_val, color) in enumerate(stats_config):
            card = QFrame()
            card.setObjectName(f"statCard_{key}")
            _card_bg = TokenManager.instance().get_qcolor("bg.base")
            _card_bg.setAlphaF(0.85)
            card.setStyleSheet(f"""
                QFrame#statCard_{key} {{
                    background-color: rgba({_card_bg.red()}, {_card_bg.green()}, {_card_bg.blue()}, 0.85);
                    border: 1px solid {color}40;
                    border-radius: {self._spacing('corner.sm', 6)}px;
                }}
            """)
            card.setFixedHeight(90)

            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 12, 16, 12)
            cl.setSpacing(4)

            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {self._color('text.tertiary')}; font-size: {self._font_size('xs', 11)}px; background: transparent; border: none;")
            cl.addWidget(lbl)

            val = QLabel(default_val)
            val.setObjectName(f"statVal_{key}")
            val.setFont(QFont("Monoton", 22))
            val.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            cl.addWidget(val)
            self._stat_labels[key] = val

            sub_lbl = QLabel("")
            sub_lbl.setObjectName(f"statSub_{key}")
            sub_lbl.setStyleSheet(f"color: {self._color('neutral.dark')}; font-size: {self._font_size('micro', 10)}px; background: transparent; border: none;")
            cl.addWidget(sub_lbl)
            self._stat_labels[f"{key}_sub"] = sub_lbl

            row, col = divmod(i, 3)
            stats_layout.addWidget(card, row, col)

        layout.addWidget(stats_container)

        # ── 数据管理 ──
        mgmt_card = CyberCard(title=self._copy("status.card_mgmt", "数据管理"))
        mgmt_layout = mgmt_card.content_layout()
        mgmt_layout.setContentsMargins(16, 28, 16, 16)
        mgmt_layout.setSpacing(12)

        # 更新基础数据按钮（主按钮）
        self._btn_update = CyberButton(text=self._copy("status.btn_update", "更新基础数据"), variant="solid")
        self._btn_update.setToolTip(self._copy("status.tip_update", "从 WFCD 拉取最新遗物/物品/掉落/翻译数据"))
        self._btn_update.clicked.connect(self._on_update_base_data)
        mgmt_layout.addWidget(self._btn_update)

        # 辅助按钮行
        sub_row = QHBoxLayout()
        sub_row.setSpacing(10)

        btn_mirror = CyberButton(text=self._copy("status.btn_mirror", "镜像设置"), variant="outlined")
        btn_mirror.setToolTip(self._copy("status.tip_mirror", "配置 GitHub 代理镜像列表，解决国内访问问题"))
        btn_mirror.clicked.connect(self._on_open_proxy_config)
        sub_row.addWidget(btn_mirror)

        btn_dir = CyberButton(text=self._copy("status.btn_dir", "打开数据目录"), variant="ghost")
        btn_dir.setToolTip(self._copy("status.tip_dir", "在文件管理器中打开 data/ 文件夹"))
        btn_dir.clicked.connect(self._on_open_data_dir)
        sub_row.addWidget(btn_dir)

        btn_refresh = CyberButton(text=self._copy("status.btn_refresh_stat", "刷新统计"), variant="ghost")
        btn_refresh.clicked.connect(self._refresh_all_stats)
        sub_row.addWidget(btn_refresh)

        sub_row.addStretch()

        # 状态标签
        self._update_status_label = QLabel("")
        self._update_status_label.setStyleSheet(
            f"color: {self._color('neutral.dark')}; font-size: {self._font_size('xs', 11)}px; background: transparent; border: none;"
        )
        sub_row.addWidget(self._update_status_label)

        mgmt_layout.addLayout(sub_row)

        layout.addWidget(mgmt_card)

        # ── 操作日志 ──
        log_card = CyberCard(title=self._copy("status.card_log", "操作日志"))
        log_layout = log_card.content_layout()
        log_layout.setContentsMargins(16, 28, 16, 16)
        log_layout.setSpacing(8)

        self._log_viewer = CyberLogViewer(title="", max_lines=300)
        log_layout.addWidget(self._log_viewer)

        # ── 进度条（更新时显示） ──
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("%p%")
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)  # 默认隐藏
        self._progress_bar.setFixedHeight(22)
        accent = self._color("accent.primary")
        _pb_bg = TokenManager.instance().get_qcolor("bg.raised")
        _pb_end = TokenManager.instance().get_qcolor("semantic.warning")
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {_pb_bg.name()};
                border: 1px solid {accent}40;
                border-radius: {self._spacing('corner.xs', 4)}px;
                text-align: center;
                color: {accent};
                font-size: {self._font_size('sm', 11)}px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent}, stop:1 {_pb_end.name()});
                border-radius: {self._spacing('corner.xs', 4)}px;
            }}
        """)
        log_layout.addWidget(self._progress_bar)

        layout.addWidget(log_card)
        layout.addStretch()

        return container

    # ── 子组件构建 ──

    def _build_status_card(self) -> QFrame:
        """构建数据库状态卡片。"""
        card = QFrame()
        card.setObjectName("dbStatusCard")
        _dbg_bg = TokenManager.instance().get_qcolor("bg.base")
        card.setStyleSheet(f"""
            QFrame#dbStatusCard {{
                background-color: rgba({_dbg_bg.red()}, {_dbg_bg.green()}, {_dbg_bg.blue()}, 0.85);
                border: 1px solid {self._color('alias.border.default')};
                border-radius: {self._spacing('corner.md', 8)}px;
            }}
        """)
        card.setFixedHeight(70)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(20)

        self._status_indicator = QLabel("\u25cf")
        self._status_indicator.setStyleSheet(
            f"color: {self._color('neutral.dark')}; font-size: {self._font_size('xxl', 24)}px; background: transparent; border: none;"
        )
        layout.addWidget(self._status_indicator)

        self._status_text = QLabel(self._copy("common.detecting", "检测中..."))
        self._status_text.setStyleSheet(
            f"color: {self._color('text.secondary')}; font-size: {self._font_size('sm_md', 13)}px; background: transparent; border: none;"
        )
        layout.addWidget(self._status_text)

        layout.addStretch()

        self._db_info_label = QLabel("")
        self._db_info_label.setStyleSheet(
            f"color: {self._color('neutral.dark')}; font-size: {self._font_size('xs', 11)}px; background: transparent; border: none;"
        )
        layout.addWidget(self._db_info_label)

        return card

    # ── 数据刷新 ──

    def _refresh_all_stats(self) -> None:
        """刷新所有统计数据。"""
        self._log_viewer.add_log("info", self._copy("status.log_refresh_start", "开始刷新统计数据..."), "stats")

        stats = self._fetch_db_stats()

        if not stats.get("exists"):
            self._set_no_db_state()
            return

        self._set_connected_state(stats)

        self._update_stat_label("relics_total", str(stats.get("relics", 0)), self._copy("status.unit_relics", "种遗物"))
        self._update_stat_label("items_total", f"{stats.get('items', 0):,}", self._copy("status.unit_items", "条物品记录"))
        self._update_stat_label("translations", f"{stats.get('translations', 0):,}", self._copy("status.unit_translations", "条翻译"))
        self._update_stat_label("relic_rewards", f"{stats.get('parts', 0):,}", self._copy("status.unit_rewards", "个奖励部件"))
        self._update_stat_label("vaulted", str(stats.get("vaulted", 0)), self._copy("status.unit_vaulted", "入库"))
        self._update_stat_label("available", str(stats.get("available", 0)), self._copy("status.unit_available", "出库"))

        self._log_viewer.add_log(
            "ok",
            self._copy("status.log_refresh_done", "统计刷新完成 — {items} 物品 / {relics} 遗物", items=stats.get('items', 0), relics=stats.get('relics', 0)),
            "stats",
        )

    def _fetch_db_stats(self) -> dict:
        """从数据库获取统计数据。"""
        if not os.path.exists(self._db_path):
            return {"exists": False}

        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            cur = conn.cursor()

            relics = cur.execute(
                "SELECT COUNT(DISTINCT tier || ' ' || relic_name) FROM relics"
            ).fetchone()[0]
            vaulted = cur.execute(
                "SELECT COUNT(DISTINCT tier || ' ' || relic_name) FROM relics WHERE vaulted=1"
            ).fetchone()[0]
            parts = cur.execute("SELECT COUNT(*) FROM relic_rewards").fetchone()[0]
            items = cur.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            translations = cur.execute("SELECT COUNT(*) FROM game_translations").fetchone()[0]

            conn.close()

            stat = os.stat(self._db_path)
            return {
                "exists": True,
                "relics": relics,
                "parts": parts,
                "vaulted": vaulted,
                "available": relics - vaulted,
                "items": items,
                "translations": translations,
                "db_size": stat.st_size,
                "db_mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }

        except sqlite3.DatabaseError as e:
            self._log_viewer.add_log("error", self._copy("status.log_db_error", "数据库错误: {err}", err=e), "db")
            return {"exists": False, "error": str(e)}
        except Exception as e:
            self._log_viewer.add_log("error", self._copy("status.log_read_error", "读取失败: {err}", err=e), "db")
            return {"exists": False, "error": str(e)}

    # ── UI 更新辅助 ──

    def _update_stat_label(self, key: str, value: str, sub_text: str) -> None:
        """更新单个统计标签。"""
        if key in self._stat_labels:
            self._stat_labels[key].setText(value)
        if f"{key}_sub" in self._stat_labels:
            self._stat_labels[f"{key}_sub"].setText(sub_text)

    def _set_connected_state(self, stats: dict) -> None:
        """设置已连接状态的 UI。"""
        self._status_indicator.setStyleSheet(
            f"color: {self._color('brand.green')}; font-size: {self._font_size('xxl', 24)}px; background: transparent; border: none;"
        )
        self._status_text.setText(self._copy("status.db_ok", "数据库连接正常"))
        size_mb = stats.get("db_size", 0) / (1024 * 1024)
        mtime = stats.get("db_mtime", "--")
        self._db_info_label.setText(f"{size_mb:.1f} MB | 更新于 {mtime}")

    def _set_no_db_state(self) -> None:
        """设置无数据库状态的 UI。"""
        self._status_indicator.setStyleSheet(
            f"color: {self._color('brand.red')}; font-size: {self._font_size('xxl', 24)}px; background: transparent; border: none;"
        )
        self._status_text.setText(self._copy("status.db_missing", "数据库文件不存在"))
        self._db_info_label.setText(f"路径: {self._db_path}")

        for key in list(self._stat_labels.keys()):
            if not key.endswith("_sub"):
                self._stat_labels[key].setText("--")

        self._log_viewer.add_log("error", self._copy("status.log_db_not_found", "数据库不存在: {path}", path=self._db_path), "db")

    # ── 数据管理操作 ──

    def _on_update_base_data(self) -> None:
        """更新基础数据（WFCD -> warframe.db）。"""
        if self._updating:
            self._log_viewer.add_log("warn", self._copy("status.log_update_busy", "正在更新中，请勿重复点击..."), "pipeline")
            return

        reply = QMessageBox.question(
            self, self._copy("status.update_confirm_title", "更新基础数据"),
            self._copy("status.update_confirm_body", "将从 WFCD 拉取最新遗物/物品/掉落/翻译数据。\n\n是否继续？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._updating = True
        self._btn_update.setEnabled(False)
        self._update_status_label.setText(self._copy("status.updating", "更新中..."))
        self._log_viewer.add_log("info", self._copy("status.log_pipeline_start", "========== 更新基础数据 =========="), "pipeline")
        self._log_viewer.add_log("info", self._copy("status.log_pipeline_flow", "流水线: WFCD → warframe.db"), "pipeline")

        # ── 所有 Qt 对象必须在主线程创建 ──
        try:
            from core.services.pipeline import DataPipelineWorker
            from core.services.db_connections import close_all_db_connections

            # Worker 和 Bridge 都在主线程创建，确保线程安全
            worker = DataPipelineWorker(close_connections_fn=close_all_db_connections)

            class _PipelineBridge(QObject):
                log_sig = QtSignal(str, str)
                step_sig = QtSignal(int, str)
                progress_sig = QtSignal(int)
                finished_sig = QtSignal(dict)
                error_sig = QtSignal(str)

            bridge = _PipelineBridge()
            self._pipeline_bridge = bridge  # 防止 GC

            # 显示进度条，重置状态
            self._progress_bar.setVisible(True)
            self._progress_bar.setValue(0)

            def _on_log(level, msg):
                self._log_viewer.add_log(level, msg, "pipeline")

            def _on_step(step, desc):
                self._log_viewer.add_log("info", self._copy("status.log_pipeline_step", "[步骤 {step}] {desc}", step=step, desc=desc), "pipeline")

            def _on_progress(pct):
                self._update_status_label.setText(self._copy("status.log_update_progress", "更新中... {pct}%", pct=pct))
                self._progress_bar.setValue(min(pct, 100))

            def _on_finished(result):
                self._updating = False
                self._btn_update.setEnabled(True)
                self._pipeline_bridge = None
                self._progress_bar.setVisible(False)  # 隐藏进度条
                if result.get("semantic.success"):
                    elapsed = result.get("elapsed", 0)
                    self._log_viewer.add_log(
                        "ok",
                        self._copy("status.update_complete", "基础数据更新完成! 总耗时: {elapsed:.0f}s", elapsed=elapsed),
                        "pipeline",
                    )
                    self._update_status_label.setText("")
                    QTimer.singleShot(500, self._refresh_all_stats)
                else:
                    err = result.get("error", "未知错误")
                    self._log_viewer.add_log("error", self._copy("status.pipeline_fail", "流水线失败: {err}", err=err), "pipeline")
                    self._update_status_label.setText(self._copy("status.update_fail", "更新失败"))
                    QMessageBox.warning(
                        self, self._copy("status.update_fail_title", "更新失败"),
                        self._copy("status.update_fail_body", "部分数据库更新失败:\n{err}\n\n已完成的步骤不受影响。", err=err),
                    )

            def _on_error(err_msg):
                self._updating = False
                self._btn_update.setEnabled(True)
                self._pipeline_bridge = None
                self._progress_bar.setVisible(False)  # 隐藏进度条
                self._log_viewer.add_log("error", self._copy("status.pipeline_error", "流水线错误: {err_msg}", err_msg=err_msg), "pipeline")
                self._update_status_label.setText(self._copy("status.update_error", "出错"))

            bridge.log_sig.connect(_on_log)
            bridge.step_sig.connect(_on_step)
            bridge.progress_sig.connect(_on_progress)
            bridge.finished_sig.connect(_on_finished)
            bridge.error_sig.connect(_on_error)

            worker.step_changed.connect(lambda s, d: bridge.step_sig.emit(s, d))
            worker.log.connect(lambda l, m: bridge.log_sig.emit(l, m))
            worker.progress_pct.connect(lambda p: bridge.progress_sig.emit(p))
            worker.finished.connect(lambda r: bridge.finished_sig.emit(r))
            worker.error.connect(lambda e: bridge.error_sig.emit(e))

        except ImportError as e:
            self._updating = False
            self._btn_update.setEnabled(True)
            self._progress_bar.setVisible(False)
            self._log_viewer.add_log(
                "error",
                self._copy("status.module_missing", "缺少 pipeline 模块，无法执行更新。"),
                "pipeline",
            )
            self._update_status_label.setText(self._copy("status.module_missing_status", "模块缺失"))
            print(f"[StatusPage] ImportError: {e}", flush=True)
            return
        except Exception as e:
            self._updating = False
            self._btn_update.setEnabled(True)
            self._progress_bar.setVisible(False)
            self._log_viewer.add_log("error", self._copy("status.update_exception", "更新异常: {err}", err=e), "pipeline")
            self._update_status_label.setText(self._copy("status.update_error", "出错"))
            print(f"[StatusPage] 初始化异常: {e}", flush=True)
            return

        # 启动后台线程：只执行纯 Python 的 worker.run()
        def _target():
            try:
                worker.run()
            except Exception as e:
                print(f"[StatusPage] 流水线异常: {e}", flush=True)
                import traceback
                traceback.print_exc()
                bridge.error_sig.emit(str(e))

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()

    def _run_pipeline(self) -> None:
        """保留旧接口兼容（不再使用）。
        
        注意: 此方法已废弃，所有流水线逻辑移至 _on_update_base_data 中，
        确保 Qt 对象在主线程创建，避免跨线程 QObject 崩溃。
        """
        pass

    def _on_open_proxy_config(self) -> None:
        """打开代理镜像配置对话框。"""
        from core.widgets.proxy_dialog import CyberProxyDialog

        dialog = CyberProxyDialog(parent=self)
        dialog.exec()

    def _on_open_data_dir(self) -> None:
        """打开数据目录。"""
        data_path = str(self._data_dir.resolve())
        if os.path.isdir(data_path):
            os.startfile(data_path)
            self._log_viewer.add_log("info", self._copy("status.log_dir_opened", "已打开目录: {path}", path=data_path), "user")
        else:
            self._log_viewer.add_log("warn", self._copy("status.log_dir_missing", "目录不存在: {path}", path=data_path), "user")
