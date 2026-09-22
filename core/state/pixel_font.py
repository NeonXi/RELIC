"""
[L-State] core.state.pixel_font — 像素字体持久化存储

归属层:    [L-State] (core/state/)
允许依赖:  Python 标准库(无 Qt 依赖)
禁止依赖:  PySide6 / QtWidgets(本模块是纯数据层,不能引入 UI)
          core.widgets.*(被 state 反向调用违反分层)

职责:
  - 集中存放 A-Z 26 个字母的像素字型数据(每字 16x20 网格:14 行字形 + 6 行底部装饰)
  - 提供 JSON 加载/保存/重新加载能力
  - 暴露给 splash_screen.py(只读消费,渲染"RELIC"标题)和 pixel_font_editor.py(编辑+保存)
  - 保持进程内单例缓存,reload() 时刷新缓存

原位置:  之前分散在 core/widgets/splash_screen.py(line 54-205)
        和 core/widgets/pixel_font_editor.py(line 70-83)
违反规范: §7 #2 "widgets/ 中读写 JSON"

本文件相关红线:
- 禁止 import PySide6 → 数据层不能依赖 UI
- 禁止返回 Qt 对象 → 只能返回 dict / Path
- 禁止在 IO 中做 widget 通知 → 通知由调用方走 Signal
- 禁止缓存到全局 dict 时持 widget 引用

迁移记录:
  - 2026-06-17 从 widgets 迁出,保持向后兼容的 API 命名。
  - 2026-07-27 26 字母重新设计为"硬朗几何"风格(替代原粗实心 RELIC 5 字母)
"""

# ── 标准库 ──
import json
from pathlib import Path
from typing import Optional

# ── 内置默认字型 (A-Z 26 字母, 16x20 网格 per 字母) ──
# 硬朗几何风格,2 格粗笔画,无弯曲弧线
# 底部 6 行装饰(3 空 + 1 全填充 + 1 空 + 1 全填充)由 _parse_letter_art 自动追加
# 风格说明:每个字母设计成"块状/几何切角"质感,与 Cyberpunk 主题搭调


# 字母 ASCII art(14 行 × 16 字符,# = 1, . = 0)
_LETTER_ART_A = """
....########....
...##########...
..############..
..##........##..
..##........##..
..##........##..
..##........##..
..############..
..############..
..##........##..
..##........##..
..##........##..
..##........##..
..##........##..
"""

_LETTER_ART_B = """
.###########....
#############...
.##.........##..
.##.........##..
.##.........##..
.#############..
.#############..
.##.........##..
.##.........##..
.##.........##..
.##.........##..
.#############..
.#############..
.##.........##..
"""

_LETTER_ART_C = """
..############..
.##############.
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##############.
..############..
"""

_LETTER_ART_D = """
.###########....
#############...
.##.........##..
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
#############...
.###########....
"""

_LETTER_ART_E = """
.##############.
.##############.
.##.............
.##.............
.##.............
.##.............
.#############..
.#############..
.##.............
.##.............
.##.............
.##.............
.##############.
.##############.
"""

_LETTER_ART_F = """
.##############.
.##############.
.##.............
.##.............
.##.............
.##.............
.#############..
.#############..
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
"""

_LETTER_ART_G = """
..############..
.##############.
.##.............
.##.............
.##.............
.##.....######..
.##.....######..
.##........##...
.##........##...
.##........##...
.##........##...
.##........##...
.##############.
..############..
"""

_LETTER_ART_H = """
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##############.
.##############.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
"""

_LETTER_ART_I = """
.##############.
.##############.
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
.##############.
.##############.
"""

_LETTER_ART_J = """
.##############.
.##############.
..........##....
..........##....
..........##....
..........##....
..........##....
..........##....
..........##....
.##......##.....
.##......##.....
.##......##.....
..############..
...##########...
"""

_LETTER_ART_K = """
.##.........##..
.##........##...
.##.......##....
.##......##.....
.##.....##......
.##....##.......
.#######........
.########.......
.##....##.......
.##.....##......
.##......##.....
.##.......##....
.##........##...
.##.........##..
"""

_LETTER_ART_L = """
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##############.
.##############.
"""

_LETTER_ART_M = """
.##..........##.
.###........###.
.####......####.
.######..######.
.##############.
.##############.
.##.########.##.
.##..######..##.
.##...####...##.
.##....##....##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
"""

_LETTER_ART_N = """
.##..........##.
.###.........##.
.####........##.
.#####.......##.
.######......##.
.#######.....##.
.########....##.
.#########...##.
.##########..##.
.###########.##.
.############.##
.##############.
.##........####.
.##..........##.
"""

_LETTER_ART_O = """
..############..
.##############.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##############.
..############..
"""

_LETTER_ART_P = """
.###########....
#############...
.##.........##..
.##.........##..
.##.........##..
.#############..
.#############..
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
.##.............
"""

_LETTER_ART_Q = """
..############..
.##############.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##############.
...##########...
"""

_LETTER_ART_R = """
.###########....
#############...
.##.........##..
.##.........##..
.##.........##..
.#############..
.#############..
.##....##.......
.##.....##......
.##......##.....
.##.......##....
.##........##...
.##.........##..
.##..........##.
"""

_LETTER_ART_S = """
..############..
.##############.
.##.............
.##.............
.##.............
.#############..
.#############..
...........##...
...........##...
...........##...
.##........##...
.##........##...
.##############.
..############..
"""

_LETTER_ART_T = """
.##############.
.##############.
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
......##........
"""

_LETTER_ART_U = """
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##############.
..############..
"""

_LETTER_ART_V = """
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
..##........##..
...##......##...
....########....
"""

_LETTER_ART_W = """
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##.##....##.##.
.##..##..##..##.
.##...####...##.
.##....##....##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
"""

_LETTER_ART_X = """
.##..........##.
.##..........##.
..##........##..
...##......##...
....##....##....
.....##..##.....
......####......
......####......
.....##..##.....
....##....##....
...##......##...
..##........##..
.##..........##.
.##..........##.
"""

_LETTER_ART_Y = """
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
.##..........##.
..##........##..
...##......##...
....##....##....
.....##..##.....
......####......
......##........
......##........
......##........
"""

_LETTER_ART_Z = """
.##############.
.##############.
...........##...
..........##....
.........##.....
........##......
.......##.......
......##........
.....##.........
....##..........
...##...........
..##............
.##############.
.##############.
"""


# ── 解析函数 ──

def _parse_letter_art(art: str) -> list[list[int]]:
    """ASCII art 字符串 → 16x20 像素网格。

    输入格式:
      - 每行 16 字符(`.` = 0, `#` = 1),少于此宽度的行右边自动补 0
      - 14 行字形区(超出的行被丢弃,不足的行底部补 0)
      - 本函数自动追加 6 行底部装饰(3 空 + 1 全 1 + 1 空 + 1 全 1)

    输出: list[list[int]] 形状 (20, 16)
    """
    # 取所有非空行
    lines = [ln for ln in art.strip().splitlines() if ln]
    grid: list[list[int]] = []
    for ln in lines[:14]:  # 最多 14 行
        row = [1 if c == "#" else 0 for c in ln[:16]]  # 最多 16 字符
        row += [0] * (16 - len(row))  # 不足 16 补 0
        grid.append(row)
    # 不足 14 行的底部补 0 行
    while len(grid) < 14:
        grid.append([0] * 16)
    # 追加 6 行底部装饰
    grid.append([0] * 16)  # row 14: 空
    grid.append([0] * 16)  # row 15: 空
    grid.append([0] * 16)  # row 16: 空
    grid.append([1] * 16)  # row 17: 全填充(下划线 1)
    grid.append([0] * 16)  # row 18: 空
    grid.append([1] * 16)  # row 19: 全填充(下划线 2)
    return grid


# ── 默认字型字典 ──

_DEFAULT_FONT: dict[str, list[list[int]]] = {
    ch: _parse_letter_art(art)
    for ch, art in {
        "A": _LETTER_ART_A, "B": _LETTER_ART_B, "C": _LETTER_ART_C,
        "D": _LETTER_ART_D, "E": _LETTER_ART_E, "F": _LETTER_ART_F,
        "G": _LETTER_ART_G, "H": _LETTER_ART_H, "I": _LETTER_ART_I,
        "J": _LETTER_ART_J, "K": _LETTER_ART_K, "L": _LETTER_ART_L,
        "M": _LETTER_ART_M, "N": _LETTER_ART_N, "O": _LETTER_ART_O,
        "P": _LETTER_ART_P, "Q": _LETTER_ART_Q, "R": _LETTER_ART_R,
        "S": _LETTER_ART_S, "T": _LETTER_ART_T, "U": _LETTER_ART_U,
        "V": _LETTER_ART_V, "W": _LETTER_ART_W, "X": _LETTER_ART_X,
        "Y": _LETTER_ART_Y, "Z": _LETTER_ART_Z,
    }.items()
}


# ── JSON 文件路径(打包后位于可写的用户数据目录) ──
def _compute_json_path() -> Path:
    """计算 pixel_font.json 的绝对路径(打包/开发环境自适应)。

    开发:   项目根 / data / pixel_font.json(与旧推导等价)
    打包:   exe旁 / data / pixel_font.json(不可写时降级 %LOCALAPPDATA%)
            首次启动若用户文件不存在,自动从随包只读资源复制初始模板。
    """
    from core.paths import ensure_user_file
    return ensure_user_file("pixel_font.json")


# 默认 splash 字符组合(开屏动画展示的字串)
_DEFAULT_SPLASH_TEXT: str = "RELIC"

# 特殊元数据 key(顶层 JSON 中唯一允许的非字母 art 字段)
_SPLASH_TEXT_KEY: str = "splash_text"

# 进程内单例: 加载一次,reload() 时刷新
_json_path: Path = _compute_json_path()
_cache: Optional[dict[str, list[list[int]]]] = None
_splash_text_cache: Optional[str] = None


def _validate(data) -> bool:
    """校验 JSON 数据结构是否符合像素字体的通用格式。

    不再硬编码允许的字符集(原硬编码 ("R","E","L","I","C") 会导致用户
    在编辑器加新字符后,下次启动被静默丢弃,回退到默认 — 这是历史 bug)。

    新规则:
      - 顶层可有一个特殊 key "splash_text"(值为 str,表示开屏动画字符组合)
      - 其他 key 的 value 必须是 list[list[int]]:
        * 至少 1 行
        * 每行长度一致(列数固定)
        * 每个元素是 0/1 整数(像素亮/灭)
      - 字符 key 不限制(可任意字符,包括大写字母/数字/自定义)

    校验失败的 JSON 视为损坏,降级到内置默认值。
    """
    if not isinstance(data, dict):
        return False
    if not data:
        return False
    for ch, val in data.items():
        # 特殊元数据: splash_text 必须是 str
        if ch == _SPLASH_TEXT_KEY:
            if not isinstance(val, str):
                return False
            continue
        # 字母 art: list[list[int]] 校验
        if not isinstance(val, list) or not val:
            return False
        first_row = val[0]
        if not isinstance(first_row, list) or not first_row:
            return False
        cols = len(first_row)
        for row in val:
            if not isinstance(row, list) or len(row) != cols:
                return False
            for v in row:
                if not isinstance(v, int) or v not in (0, 1):
                    return False
    return True


def _load_from_disk() -> tuple[dict[str, list[list[int]]], str]:
    """从磁盘 JSON 加载,失败时降级到内置默认值。

    返回: (letters_dict, splash_text_str)
      - letters_dict: 字母 art 字典(不包含 splash_text 字段)
      - splash_text_str: 开屏动画展示的字符组合

    IO 失败(权限/解析错误)被吞掉,fallback 到默认。
    这是合理的:启动画面必须能渲染,即使字体文件损坏。
    """
    try:
        if _json_path.exists():
            with open(_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if _validate(data):
                # 提取 splash_text,过滤后剩字母 art
                splash_text = data.get(_SPLASH_TEXT_KEY, _DEFAULT_SPLASH_TEXT)
                if not isinstance(splash_text, str):
                    splash_text = _DEFAULT_SPLASH_TEXT
                letters = {
                    k: v for k, v in data.items() if k != _SPLASH_TEXT_KEY
                }
                # 字母 art 至少要有 1 个,否则视为损坏
                if letters:
                    return letters, splash_text
    except Exception:
        # 静默失败,降级到默认字型
        pass
    # 复制一份避免外部修改影响默认
    letters = {k: [row[:] for row in v] for k, v in _DEFAULT_FONT.items()}
    return letters, _DEFAULT_SPLASH_TEXT


def _ensure_loaded() -> None:
    """首次访问时触发磁盘加载,后续直接返回缓存。"""
    global _cache, _splash_text_cache
    if _cache is None or _splash_text_cache is None:
        _cache, _splash_text_cache = _load_from_disk()


def get_pixel_font() -> dict[str, list[list[int]]]:
    """获取当前像素字体数据(进程内缓存)。

    首次调用会触发磁盘加载,后续调用直接返回缓存。
    调用方应只读,不要修改返回值(修改会影响全局缓存)。
    """
    _ensure_loaded()
    assert _cache is not None
    return _cache


def get_splash_text() -> str:
    """获取当前 splash 字符组合(开屏动画展示的字串,如 "RELIC")。

    首次调用会触发磁盘加载,后续直接返回缓存。
    """
    _ensure_loaded()
    assert _splash_text_cache is not None
    return _splash_text_cache


def set_splash_text(text: str) -> None:
    """更新 splash 字符组合(仅更新内存缓存,需要调 save_pixel_font 落盘)。

    Args:
        text: 新的 splash 字串,空字符串会被替换为 "RELIC"
    """
    global _splash_text_cache
    _ensure_loaded()
    new_text = text if text else _DEFAULT_SPLASH_TEXT
    _splash_text_cache = new_text


def save_pixel_font(
    font_data: dict[str, list[list[int]]],
    splash_text: Optional[str] = None,
) -> tuple[bool, str]:
    """保存字体数据到磁盘 JSON(包含 splash_text 顶层字段)。

    Args:
        font_data: 字母 art 字典(不包含 splash_text)
        splash_text: splash 字符组合,None 表示用当前缓存值

    返回: (成功标志, 错误信息)
        - (True, "") 表示成功
        - (False, "...") 表示失败,错误信息可展示给用户

    IO 异常(权限/磁盘/编码)被捕获,不会冒泡到 UI。
    """
    global _cache, _splash_text_cache
    try:
        if splash_text is None:
            _ensure_loaded()
            splash_text = _splash_text_cache or _DEFAULT_SPLASH_TEXT
        # 顶层组装: splash_text 元数据 + 字母 art
        full_data = {**_DEFAULT_FONT, _SPLASH_TEXT_KEY: splash_text}
        # 字母 art 优先用传入的 font_data(用户可能编辑过)
        for ch, grid in font_data.items():
            full_data[ch] = grid
        # 确保父目录存在(首次保存时 data/ 可能缺失)
        _json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(_json_path, "w", encoding="utf-8") as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)
        # 同步内存缓存
        _cache = {k: [row[:] for row in v] for k, v in full_data.items() if k != _SPLASH_TEXT_KEY}
        _splash_text_cache = splash_text
        return True, ""
    except PermissionError:
        return False, f"没有写入权限: {_json_path}"
    except OSError as e:
        return False, f"文件系统错误: {e}"
    except Exception as e:
        return False, str(e)


def reload() -> None:
    """强制重新从磁盘加载字体数据(刷新字母 art 和 splash_text 缓存)。"""
    global _cache, _splash_text_cache
    _cache, _splash_text_cache = _load_from_disk()


def get_json_path() -> Path:
    """获取 JSON 文件路径(供编辑器展示给用户)。"""
    return _json_path


def get_default_splash_text() -> str:
    """获取默认 splash 字符组合("RELIC",用于重置)。"""
    return _DEFAULT_SPLASH_TEXT
