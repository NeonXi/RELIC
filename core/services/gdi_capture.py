"""
GDI 截图模块 — 使用 Windows BitBlt API 捕获屏幕区域。
参考 WarframeMonitor 技术文档 4.2 节的 C++ 实现。

与 dxcam 的区别：
- dxcam: DirectX GPU 帧捕获，返回原始渲染缓冲区（可能含 alpha/不同色彩空间）
- GDI: Windows 桌面 BitBlt，标准 BGRA 格式，与原项目完全一致
"""

import ctypes
import ctypes.wintypes as wintypes
import numpy as np
import cv2


# ════════════════════════════════════
#  Windows 常量
# ════════════════════════════════════

SRCCOPY = 0x00CC0020

# BITMAPINFOHEADER 结构体布局
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def gdi_capture_region(left: int, top: int, right: int, bottom: int) -> np.ndarray:
    """使用 Windows GDI BitBlt 截取屏幕指定区域。

    Args:
        left, top, right, bottom: 屏幕物理坐标（像素）

    Returns:
        RGB 图像 (numpy array), shape (H, W, 3), dtype=uint8
        如果截图失败返回 None
    """
    width = right - left
    height = bottom - top

    if width <= 0 or height <= 0:
        return None

    # 1. 获取桌面 DC
    hdc_screen = ctypes.windll.user32.GetDC(0)
    if not hdc_screen:
        return None

    # 2. 创建兼容 DC 和位图
    hdc_mem = ctypes.windll.gdi32.CreateCompatibleDC(hdc_screen)
    hbitmap = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    hbitmap_old = ctypes.windll.gdi32.SelectObject(hdc_mem, hbitmap)

    # 3. BitBlt 截图
    result = ctypes.windll.gdi32.BitBlt(
        hdc_mem, 0, 0, width, height,
        hdc_screen, left, top,
        SRCCOPY
    )

    if not result:
        # 清理并退出
        ctypes.windll.gdi32.SelectObject(hdc_mem, hbitmap_old)
        ctypes.windll.gdi32.DeleteObject(hbitmap)
        ctypes.windll.gdi32.DeleteDC(hdc_mem)
        ctypes.windll.user32.ReleaseDC(0, hdc_screen)
        return None

    # 4. 获取位图数据 → numpy array (BGRA)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height  # 负值 = 从上到下（top-down）
    bmi.biPlanes = 1
    biBitCount = 32
    bmi.biBitCount = biBitCount
    bmi.biCompression = 0  # BI_RGB

    # 分配缓冲区 (BGRA, 4 字节/像素)
    buffer_size = width * height * 4
    buffer = ctypes.create_string_buffer(buffer_size)

    ctypes.windll.gdi32.GetDIBits(
        hdc_mem, hbitmap, 0, height,
        buffer, ctypes.byref(bmi), 0  # DIB_RGB_COLORS
    )

    # 5. 转换为 numpy array
    img_bgra = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)

    # 6. 清理 GDI 对象
    ctypes.windll.gdi32.SelectObject(hdc_mem, hbitmap_old)
    ctypes.windll.gdi32.DeleteObject(hbitmap)
    ctypes.windll.gdi32.DeleteDC(hdc_mem)
    ctypes.windll.user32.ReleaseDC(0, hdc_screen)

    # 7. BGRA → BGR（与 dxcam 输出一致，下游统一做 BGR→RGB）
    img_bgr = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2BGR)

    return img_bgr


def gdi_capture_fullscreen() -> np.ndarray | None:
    """使用 Windows GDI BitBlt 截取整个主屏幕。

    与原项目 WarframeMonitor 一致：截取完整游戏窗口/桌面，
    保证 DB-Net 有足够的像素密度检测文字。

    Returns:
        BGR 图像 (numpy array), shape (H, W, 3), dtype=uint8
        如果截图失败返回 None
    """
    # 获取屏幕尺寸
    w = ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN
    h = ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN

    if w <= 0 or h <= 0:
        return None

    return gdi_capture_region(0, 0, w, h)
