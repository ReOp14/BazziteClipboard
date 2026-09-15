from __future__ import annotations

import ctypes
import logging

from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

# KWindowEffects::Effect — KF6 kwindoweffects.h
_EFFECT_BLUR_BEHIND = 4
_EFFECT_BACKGROUND_CONTRAST = 5


def enable_plasma_backdrop(widget: QWidget) -> None:
    """Ask KWin to blur and contrast the wallpaper behind a translucent window."""
    handle = widget.windowHandle()
    if handle is None:
        widget.winId()
        handle = widget.windowHandle()
    if handle is None:
        return
    try:
        from shiboken6 import Shiboken
    except Exception:
        log.debug("shiboken6 is unavailable; skipping KWin blur")
        return

    try:
        lib = ctypes.CDLL("libKF6WindowSystem.so.6")
    except OSError:
        log.debug("libKF6WindowSystem is unavailable; skipping KWin blur")
        return

    window_ptr = _cpp_ptr(handle)
    region = QRegion()
    region_ptr = _cpp_ptr(region)
    if not window_ptr or not region_ptr:
        return

    try:
        available = lib._ZN14KWindowEffects17isEffectAvailableENS_6EffectE
        available.argtypes = [ctypes.c_int]
        available.restype = ctypes.c_bool
        if available(_EFFECT_BLUR_BEHIND):
            blur = lib._ZN14KWindowEffects16enableBlurBehindEP7QWindowbRK7QRegion
            blur.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p]
            blur.restype = None
            blur(window_ptr, True, region_ptr)
        if available(_EFFECT_BACKGROUND_CONTRAST):
            contrast = lib._ZN14KWindowEffects24enableBackgroundContrastEP7QWindowbdddRK7QRegion
            contrast.argtypes = [
                ctypes.c_void_p,
                ctypes.c_bool,
                ctypes.c_double,
                ctypes.c_double,
                ctypes.c_double,
                ctypes.c_void_p,
            ]
            contrast.restype = None
            contrast(window_ptr, True, 1.0, 1.0, 1.4, region_ptr)
    except Exception:
        log.debug("Could not enable KWin backdrop effects", exc_info=True)


def _cpp_ptr(obj) -> int:
    from shiboken6 import Shiboken

    try:
        ptrs = Shiboken.getCppPointer(obj)
    except Exception:
        return 0
    if not ptrs:
        return 0
    value = ptrs[0]
    return int(value)
