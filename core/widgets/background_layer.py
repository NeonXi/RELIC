"""
[L4] CyberBackgroundLayer — 窗口背景图绘制层

继承: CyberWidgetMixin + QFrame（非 QWidget 零开始）
依赖: core.widgets.base, Pillow（PIL）, PySide6
职责:
  - 在窗口最底层绘制用户选择的背景图
  - "选区优先"智能 cover：以用户裁剪选区为主体，窗口宽高比变化时
    优先从原图选区外的画面补充，原图不够补时才少量裁掉选区边缘
  - 按强度做高斯模糊（PIL，离线处理；不用 QGraphicsBlurEffect）
  - 按透明度合成图片
信号: 无（由 BackgroundService 直接调用 apply_background 驱动）

性能策略:
  - 原图加载一次；当前尺寸的清晰底图缓存一次
  - 模糊在 1/3 缩略图上进行（模糊本损细节，速度快约 9 倍），
    再放大回绘制尺寸
  - 各模糊档位 QImage 走 LRU 缓存（最多 8 档），resize/换选区时整体失效
"""

from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QFrame

from PIL import Image, ImageFilter

from core.widgets.base import CyberWidgetMixin

# 模糊档位缓存数量上限（每张 RGB 约占屏幕尺寸*3 字节）
_CACHE_MAX: int = 8
# 模糊计算的缩略比例（在 1/3 图上做高斯，再放大）
_DOWNSCALE: int = 3
# 缩略图上的最大模糊半径（等效到原尺寸约 ×3 → 最大约 30px）
_BLUR_R_MAX: float = 10.0
# 比例比较的浮点容差
_EPS: float = 1e-6
# 交互改尺寸时,停手多久后做一次高清重建(ms)
_REBUILD_DELAY_MS: int = 200


class CyberBackgroundLayer(CyberWidgetMixin, QFrame):
    """窗口最底层背景图控件。

    用法（由 AppShell 编排）::

        layer = CyberBackgroundLayer(central)
        BackgroundService.instance().set_layer(layer)
    """

    def __init__(self, parent=None):
        QFrame.__init__(self, parent)

        # 服务下发的状态
        self._img_path: Path | None = None
        self._crop: tuple | None = None  # (x,y,w,h) 原图坐标；None=整图
        self._opacity: int = 100        # 0-100
        self._blur: int = 0             # 0-100

        # 原图（PIL），仅在换图时重新加载
        self._source: Image.Image | None = None
        # 当前尺寸/选区下的清晰底图（PIL），失效时重算
        self._clear_cover: Image.Image | None = None
        # 模糊档位 LRU：blur(0-100) → QImage
        self._cache: OrderedDict[int, QImage] = OrderedDict()

        # 无独立边框/底色；未绘制区域保持透明，露出窗口主题底色
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # 延迟高清重建定时器(交互改尺寸时反复重启,停手后触发一次)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(_REBUILD_DELAY_MS)
        self._rebuild_timer.timeout.connect(self._rebuild_hq)

    # ════════════════════════════════════
    #  服务驱动接口
    # ════════════════════════════════════

    def apply_background(
        self,
        path: Path | str | None,
        crop,
        opacity: int,
        blur: int,
    ) -> None:
        """应用背景配置（BackgroundService 状态变化时调用）。

        - path/crop 变化：重新加载原图、清空缓存与清晰底图
        - opacity 变化：仅重绘（不重算图片）
        - blur 变化：优先命中缓存，未命中在绘制时惰性构建
        """
        new_path = Path(path) if path else None
        new_crop = tuple(int(v) for v in crop) if crop is not None else None
        config_changed = (
            self._img_path != new_path or self._crop != new_crop
        )

        if config_changed:
            self._rebuild_timer.stop()
            self._img_path = new_path
            self._crop = new_crop
            self._source = self._load_source(new_path)
            self._clear_cover = None
            self._cache.clear()

        self._opacity = max(0, min(100, int(opacity)))
        self._blur = max(0, min(100, int(blur)))
        self.update()

    # ════════════════════════════════════
    #  绘制（QPainter → 自绘图片 → super）
    # ════════════════════════════════════

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self._source is not None:
            qimg = self._ensure_qimage(self._blur)
            if qimg is not None:
                painter.setOpacity(self._opacity / 100.0)
                if qimg.width() == self.width() and \
                        qimg.height() == self.height():
                    # 尺寸一致:直接绘制高清图
                    painter.drawImage(0, 0, qimg)
                else:
                    # 交互改尺寸中:用 cover 算法绘制旧尺寸图(保留比例,不扭曲),
                    # 停手后由 _rebuild_hq 重建为当前尺寸高清图
                    # 性能与 free stretch 相当(仅一次 drawImage 调用),
                    # 但视觉上不因窗口宽高比变化而变形
                    tw, th = self.width(), self.height()
                    iw, ih = qimg.width(), qimg.height()
                    if iw > 0 and ih > 0 and tw > 0 and th > 0:
                        target_r = tw / th
                        img_r = iw / ih
                        if target_r > img_r:
                            # 窗口更宽:以宽度为基准等比放大,
                            # 高度方向从旧图上下两端各裁切一部分
                            source_w = float(iw)
                            source_h = iw / target_r
                            source_x = 0.0
                            source_y = (ih - source_h) / 2.0
                        else:
                            # 窗口更高:以高度为基准等比放大,
                            # 宽度方向从旧图左右两端各裁切一部分
                            source_h = float(ih)
                            source_w = ih * target_r
                            source_x = (iw - source_w) / 2.0
                            source_y = 0.0
                        painter.drawImage(
                            QRectF(0, 0, tw, th),
                            qimg,
                            QRectF(source_x, source_y, source_w, source_h),
                        )

        painter.end()
        super().paintEvent(event)  # QFrame：NoFrame 时无实际绘制

    def resizeEvent(self, event):
        """尺寸变化:不立即重算,重启延迟高清重建定时器。

        拖动期间 paintEvent 直接拉伸旧图(毫秒级);停手
        _REBUILD_DELAY_MS 后才做一次 LANCZOS 高清重建。
        """
        super().resizeEvent(event)
        if self._source is not None:
            self._rebuild_timer.start()
        self.update()

    def _rebuild_hq(self) -> None:
        """停手后触发:清空旧尺寸缓存,按当前尺寸高清重建。"""
        self._clear_cover = None
        self._cache.clear()
        self.update()

    # ════════════════════════════════════
    #  图片构建
    # ════════════════════════════════════

    @staticmethod
    def _load_source(path: Path | None) -> Image.Image | None:
        """PIL 加载原图（PIL 原生支持中文路径）。失败返回 None。"""
        if path is None:
            return None
        try:
            return Image.open(path).convert("RGB")
        except Exception as e:
            print(f"[BackgroundLayer] 背景图加载失败 {path}: {e}", flush=True)
            return None

    def _ensure_qimage(self, blur: int) -> QImage | None:
        """取指定模糊档位的 QImage：缓存命中直接返回，否则构建并入缓存。"""
        cached = self._cache.get(blur)
        if cached is not None:
            self._cache.move_to_end(blur)
            return cached

        w, h = self.width(), self.height()
        if w <= 0 or h <= 0 or self._source is None:
            return None

        cover = self._ensure_clear_cover(w, h)
        if cover is None:
            return None

        pil_img = cover if blur == 0 else self._apply_blur(cover, blur, w, h)
        qimg = self._pil_to_qimage(pil_img)
        if qimg is not None:
            self._cache[blur] = qimg
            self._cache.move_to_end(blur)
            while len(self._cache) > _CACHE_MAX:
                self._cache.popitem(last=False)
        return qimg

    def _ensure_clear_cover(self, w: int, h: int) -> Image.Image | None:
        """当前尺寸的清晰底图（缓存；失效则重算）。

        步骤：在原图中解出"选区优先"取图区域 → 裁出该区域 → 缩放到窗口。
        """
        if self._clear_cover is not None:
            return self._clear_cover
        try:
            x, y, rw, rh = self._resolve_region(w, h)

            # float 区域 → 整数 crop box（向外取整，缩放后无接缝）
            sw_i, sh_i = self._source.width, self._source.height
            left = max(0, int(math.floor(x)))
            top = max(0, int(math.floor(y)))
            right = min(sw_i, int(math.ceil(x + rw)))
            bottom = min(sh_i, int(math.ceil(y + rh)))

            piece = self._source.crop((left, top, right, bottom))
            self._clear_cover = piece.resize((w, h), Image.LANCZOS)
        except Exception as e:
            print(f"[BackgroundLayer] 底图构建失败: {e}", flush=True)
            return None
        return self._clear_cover

    def _resolve_region(self, w: int, h: int) -> tuple[float, float, float, float]:
        """解"选区优先"取图区域（原图坐标，float）。

        术语：cover 指"铺满不留白"。窗口与选区宽高比不同时：
          1) 先尝试保持选区完整，向两侧原图借画面；
          2) 两侧原图不够借，才用满原图边界，对选区做少量居中裁剪。
        crop=None 等价于选区=整图，退化为标准居中 cover。
        """
        SW = float(self._source.width)
        SH = float(self._source.height)

        if self._crop is None:
            cx, cy, cw, ch = 0.0, 0.0, SW, SH
        else:
            x0, y0, cw0, ch0 = self._crop
            # 钳制到原图内（配置里的选区可能因换图等原因越界）
            cx = max(0.0, min(float(x0), SW - 1.0))
            cy = max(0.0, min(float(y0), SH - 1.0))
            cw = max(1.0, min(float(cw0), SW - cx))
            ch = max(1.0, min(float(ch0), SH - cy))

        target_r = w / h
        crop_r = cw / ch

        if abs(target_r - crop_r) < _EPS:
            return cx, cy, cw, ch

        if target_r < crop_r:
            # 窗口更"高瘦"：优先向上、下补画面
            need_h = cw / target_r
            extra = need_h - ch
            avail_a = cy               # 选区上方可用
            avail_b = SH - cy - ch      # 选区下方可用
            if avail_a + avail_b + _EPS >= extra:
                pa, pb = self._split_pad(extra, avail_a, avail_b)
                return cx, cy - pa, cw, need_h
            # 上下不够补：用满整高，水平方向裁选区
            rw = SH * target_r
            rx = cx + (cw - rw) / 2.0
            rx = max(0.0, min(rx, SW - rw))
            return rx, 0.0, rw, SH

        # 窗口更"宽扁"：优先向左、右补画面
        need_w = ch * target_r
        extra = need_w - cw
        avail_a = cx               # 选区左方可用
        avail_b = SW - cx - cw     # 选区右方可用
        if avail_a + avail_b + _EPS >= extra:
            pa, pb = self._split_pad(extra, avail_a, avail_b)
            return cx - pa, cy, need_w, ch
        # 左右不够补：用满整宽，垂直方向裁选区
        rh = SW / target_r
        ry = cy + (ch - rh) / 2.0
        ry = max(0.0, min(ry, SH - rh))
        return 0.0, ry, SW, rh

    @staticmethod
    def _split_pad(
        extra: float, avail_a: float, avail_b: float
    ) -> tuple[float, float]:
        """向两侧借 ``extra`` 画面（调用方已保证两侧总和足够）。

        尽量两侧均分；某一侧空间不足时，剩余量全由另一侧承担。
        """
        pa = min(extra / 2.0, avail_a)
        pb = extra - pa
        if pb > avail_b:
            pb = avail_b
            pa = extra - pb
        return pa, pb

    @staticmethod
    def _apply_blur(
        cover: Image.Image, blur: int, w: int, h: int
    ) -> Image.Image:
        """在 1/3 缩略图上高斯模糊，再放大回绘制尺寸。

        强度 0-100 用 1.5 次幂映射到缩略图半径 0-10px：
        小值更细腻，大值快速变糊（等效原尺寸最大约 30px）。
        """
        sw = max(1, w // _DOWNSCALE)
        sh = max(1, h // _DOWNSCALE)
        radius = (blur / 100.0) ** 1.5 * _BLUR_R_MAX
        small = cover.resize((sw, sh), Image.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(radius=radius))
        return small.resize((w, h), Image.BILINEAR)

    @staticmethod
    def _pil_to_qimage(img: Image.Image) -> QImage | None:
        """PIL RGB → QImage（深拷贝，脱离临时字节缓冲）。"""
        try:
            w, h = img.size
            data = img.tobytes("raw", "RGB")
            qimg = QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888)
            return qimg.copy()
        except Exception as e:
            print(f"[BackgroundLayer] PIL→QImage 转换失败: {e}", flush=True)
            return None
