# 计划:全局主窗口透明度调节

## Context(为什么做)

用户希望以**最少代码**给主面板加一个透明度滑块(30%~100%),让主窗口的 UI 透明度可调。

明确边界:
- **本次只调主窗口** `AppShell` 的 `setWindowOpacity`,不联动任何 overlay(CD 辅助/护眼遮罩/截图浮窗)
- 用户后续会单独给 overlay 做透明度调节,本次不混入
- 走纯 JSON 持久化,不动 yaml token 的"设计值"层

预期产出:主题换肤页底部新增"界面透明度"卡片,滑动滑块 → 实时调主窗口 + 落盘 `data/ui_prefs.json`,重启后保留。

---

## 设计决策(已与用户确认)

| 维度 | 选择 |
|---|---|
| 范围 | 30% ~ 100%(防止 30% 以下文字不可读) |
| 覆盖 | **只动主窗口**(QMainWindow.setWindowOpacity) |
| UI 位置 | 主题换肤页底部新增卡片 |
| 持久化 | `data/ui_prefs.json`,实时保存(拖动即写) |
| Service 形态 | 纯模块函数(参考 `core/hotkey_config.py`),不引入 QObject |

---

## 涉及文件(4 个,新增 1 + 改 3)

### 1. 新建 `core/services/ui_prefs.py` — L-Service 纯逻辑(~50 行)

职责:`data/ui_prefs.json` 的 load/save,目前只存 `window_opacity` 一个键,后续可扩。

**复用模板**:
- 路径算法抄 [core/hotkey_config.py:63-67](file:///d:/MyProgram/WARFRAME-RELIC/core/hotkey_config.py#L63-L67)
- JSONDecodeError 兜底抄 [core/hotkey_config.py:70-87](file:///d:/MyProgram/WARFRAME-RELIC/core/hotkey_config.py#L70-L87)

**关键代码骨架**:
```python
# [L-Service] core/services.ui_prefs — 全局 UI 偏好(透明度等)
# 依赖: Python 标准库 + data/ 模块
# 禁止: PySide6
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

_DEFAULT_OPACITY = 100  # 默认满透明
_MIN_OPACITY = 30       # 30% 以下不可读


def _prefs_path() -> Path:
    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "ui_prefs.json"


def load_window_opacity() -> int:
    """读取主窗口透明度百分比(30-100),失败回默认。"""
    path = _prefs_path()
    if not path.exists():
        return _DEFAULT_OPACITY
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        v = int(data.get("window_opacity", _DEFAULT_OPACITY))
        return max(_MIN_OPACITY, min(100, v))
    except (json.JSONDecodeError, ValueError, OSError):
        return _DEFAULT_OPACITY


def save_window_opacity(pct: int) -> bool:
    """保存主窗口透明度百分比(自动钳制 30-100)。"""
    pct = max(_MIN_OPACITY, min(100, int(pct)))
    try:
        path = _prefs_path()
        # 读旧值,合并(保留将来扩展字段)
        old: dict = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    old = json.load(f) or {}
            except Exception:
                old = {}
        old["window_opacity"] = pct
        with open(path, "w", encoding="utf-8") as f:
            json.dump(old, f, indent=2, ensure_ascii=False)
        return True
    except OSError:
        return False
```

---

### 2. 改 `core/app_shell.py` — 加 2 个小改动

**改动 A:在 `__init__` 末尾(`_setup_window` 之后或之内)应用初始透明度**

位置:[core/app_shell.py:198-211](file:///d:/MyProgram/WARFRAME-RELIC/core/app_shell.py#L198-L211) 的 `_setup_window` 末尾(在 setStyleSheet 之后)。

```python
# 在 _setup_window() 末尾加:
try:
    from core.services.ui_prefs import load_window_opacity
    self.setWindowOpacity(load_window_opacity() / 100.0)
except Exception:
    pass  # 默认 1.0,不阻塞启动
```

**改动 B:加一个公开方法供 Page 调用**

位置:在 `set_app_shell`/`_create_trigger_manager` 之后,任意方便位置(如 `_setup_window` 后面)。

```python
def apply_window_opacity(self, pct: int) -> None:
    """应用主窗口透明度(30-100)。由 ThemePage 滑块拖动时调用。"""
    pct = max(30, min(100, int(pct)))
    self.setWindowOpacity(pct / 100.0)
```

不需新增 `self._ui_prefs_svc` 字段(纯模块函数更轻)。

---

### 3. 改 `core/pages/theme_page.py` — 加一张卡片

**3a. `__init__` 加 UI 引用声明(必须早于 `super().__init__()`)**

位置:[core/pages/theme_page.py:47-49](file:///d:/MyProgram/WARFRAME-RELIC/core/pages/theme_page.py#L47-L49) 之前。

```python
# 透明度滑块相关引用(必须在 super().__init__() 之前声明,
# 因为 PageBase.__init__ 会调用 build_content)
from PySide6.QtWidgets import QSlider   # 已 import 过的话不要重复

self._opacity_slider: QSlider | None = None
self._opacity_label: QLabel | None = None
self._opacity_pct: int = 100  # 默认占位,on_enter 时用 service 覆盖
```

**3b. 在 `build_content` 末尾(`return container` 之前)加一张卡片**

模板:完全照搬 [eye_mask_page.py:442-489](file:///d:/MyProgram/WARFRAME-RELIC/core/pages/eye_mask_page.py#L442-L489),只改:
- `setRange(30, 100)`(原 5-80)
- 回调改为调 `app_shell.apply_window_opacity()` + `save_window_opacity()`

**3c. 在 `on_enter` 时从磁盘读最新值并同步 slider**

模板:照抄 [toggles_page.py:on_enter() 同步 checkbox 模式](file:///d:/MyProgram/WARFRAME-RELIC/core/pages/toggles_page.py),加 5 行。

**3d. 回调 `_on_opacity_changed`**

```python
def _on_opacity_changed(self, value: int) -> None:
    self._opacity_pct = value
    if self._opacity_label:
        self._opacity_label.setText(f"{value}%")
    if self._app_shell:
        self._app_shell.apply_window_opacity(value)
    from core.services.ui_prefs import save_window_opacity
    save_window_opacity(value)  # 实时落盘
```

---

### 4. 改 `data/presets/cyberpunk.yaml` — 加 3 行 token

位置:[data/presets/cyberpunk.yaml:646](file:///d:/MyProgram/WARFRAME-RELIC/data/presets/cyberpunk.yaml#L646) 之后(`theme:` 块尾)。

```yaml
card_window_opacity: "界面透明度"
label_window_opacity: "主窗口透明度"
tip_window_opacity: "30% = 几乎透明   100% = 完全不透明   (仅主窗口,不影响悬浮窗)"
```

UI 引用方式:`self._copy("theme.card_window_opacity", "界面透明度")`,与现有 L65/L114 风格一致。

---

## 不做的事(明确边界)

- ❌ 不动 CD 辅助 / 护眼遮罩 / 截图浮窗的透明度
- ❌ 不创建新 Widget 类(直接用原生 QSlider + QSS,参考 eye_mask_page)
- ❌ 不引入 Service 单例 / Signal(纯模块函数足够,后续扩字段也够用)
- ❌ 不在 Token yaml 里加 `opacity.*` 数值 token(透明度是用户偏好,不是设计 token)
- ❌ 不改 `data/feature_toggles.json`(已污染在前,不在本次范围)

---

## 验证清单(End-to-End)

1. **冷启动** — 第一次启动时滑块默认 100,主窗口完全不透明
2. **拖动到 50** — 主窗口立即变半透明,label 实时显示 "50%",`data/ui_prefs.json` 立即出现
3. **重启** — 启动后窗口按保存的 50% 显示,滑块进入主题页时自动同步到 50
4. **钳制测试** — 滑块物理上没法拖到 30 以下(已 setRange),但若手动编辑 json 写 0 或 999,`load_window_opacity()` 会被钳制回 30~100
5. **边界用例**:
   - 拖动时切到其它页面,再切回来 — slider 仍显示正确值(因 on_enter 重新读盘)
   - overlay 同步测试 — 开启护眼遮罩(50%)同时主窗口 50%,遮罩仍按自己 50% 显示,**不受主窗口影响**(符合用户要求)
   - json 文件被删/损坏 — 自动回退默认 100,不报错
6. **规范自查**:
   - [ ] `core/services/ui_prefs.py` 不 import PySide6
   - [ ] `app_shell.py` 改动在 8 行以内
   - [ ] `theme_page.py` 改动只新增卡片 + on_enter 同步,不改原有 card_startup/card_pixel_font
   - [ ] yaml 新增 3 行,放 `theme:` 块尾
   - [ ] 文案走 `_copy()`,中文作 fallback

---

## 实施顺序(3 步,~15 分钟)

1. **Step 1**:新建 `core/services/ui_prefs.py`(纯函数,无依赖)
2. **Step 2**:改 `core/app_shell.py`(加 2 段 ~8 行)
3. **Step 3**:改 `core/pages/theme_page.py`(加卡片 + on_enter 同步)+ 改 yaml(3 行)
4. **Step 4**:手动验证上述 6 项

中途**不需要**用户决策(所有边界已在本次分析中确认)。如需调整(比如范围想改成 40-100),实施时随时告诉我。
