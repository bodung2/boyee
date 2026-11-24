"""부스 동안 윈도우가 프로그램을 멈추지 않게 한다(윈도우가 아니면 아무것도 하지 않음).

- 절전 막기: 이 프로그램이 켜져 있는 동안 PC가 잠들지 않게 한다(화면 끄기는 괜찮음). 끝나면 원래대로.
- 빠른 편집 끄기: PowerShell 창 안을 마우스로 누르면 '선택' 상태가 되어 프로그램이 Esc를 누를 때까지 멈춘다.
  이 창에서만 그 기능을 끈다.
"""
from __future__ import annotations

import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
STD_INPUT_HANDLE = -10


def keep_awake() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))


def allow_sleep() -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def no_quick_edit_mode(mode: int) -> int:
    return (mode & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS


def disable_quick_edit() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    handle = k.GetStdHandle(STD_INPUT_HANDLE)
    mode = wintypes.DWORD()
    if not k.GetConsoleMode(handle, ctypes.byref(mode)):
        return False                                 # 콘솔 창이 아니면(예약 작업 등) 그냥 둔다
    return bool(k.SetConsoleMode(handle, no_quick_edit_mode(mode.value)))
