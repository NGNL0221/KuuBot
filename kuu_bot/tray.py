import ctypes
from ctypes import wintypes

WM_USER = 0x0400
WM_TRAY = WM_USER + 100
NIM_ADD = 0; NIM_DELETE = 2
NIF_ICON = 2; NIF_MESSAGE = 1; NIF_TIP = 4
MF_STRING = 0
TPM_RIGHTALIGN = 8; TPM_BOTTOMALIGN = 0x20; TPM_RETURNCMD = 0x100
ID_EXIT = 1002

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256), ("uTimeout", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint), ("style", ctypes.c_uint),
        ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", wintypes.HICON),
    ]


def _make_icon():
    data = bytearray(16 * 16 * 4)
    cx, cy, r2 = 7.5, 7.5, 6.5 * 6.5
    for y in range(16):
        for x in range(16):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            idx = (y * 16 + x) * 4
            if d2 <= r2:
                data[idx] = 50; data[idx + 1] = 150; data[idx + 2] = 255; data[idx + 3] = 255
            elif d2 <= r2 + 4:
                t = (d2 - r2) / 4.0; a = int(255 * (1 - t))
                data[idx] = 50; data[idx + 1] = 150; data[idx + 2] = 255; data[idx + 3] = a

    hdc = ctypes.windll.gdi32.CreateCompatibleDC(None)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = 16; bmi.bmiHeader.biHeight = -16
    bmi.bmiHeader.biPlanes = 1; bmi.bmiHeader.biBitCount = 32

    ppv = ctypes.c_void_p()
    hb = ctypes.windll.gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(ppv), None, 0)
    n = 16 * 16 * 4
    dst = (ctypes.c_uint8 * n).from_address(ppv.value)
    src = (ctypes.c_uint8 * n).from_buffer(data)
    ctypes.memmove(dst, src, n)

    mb = (ctypes.c_uint8 * 32)()
    for i in range(32): mb[i] = 0xFF
    hm = ctypes.windll.gdi32.CreateBitmap(16, 16, 1, 1, mb)

    ii = ICONINFO(); ii.fIcon = True; ii.hbmColor = hb; ii.hbmMask = hm
    hi = ctypes.windll.user32.CreateIconIndirect(ctypes.byref(ii))
    ctypes.windll.gdi32.DeleteObject(hb); ctypes.windll.gdi32.DeleteObject(hm)
    ctypes.windll.gdi32.DeleteDC(hdc)
    return hi


class KuuTray:
    def __init__(self, exit_cb):
        self._exit_cb = exit_cb
        self._hwnd = None; self._hicon = None

    def start(self):
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        u32 = ctypes.windll.user32
        u32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
        u32.DefWindowProcW.restype = ctypes.c_longlong

        cls = "KuuBotTrayV2"

        @ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
        def wp(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY:
                if lparam == 0x0205 or lparam == 0x0204:  # WM_RBUTTONUP/DOWN
                    menu = u32.CreatePopupMenu()
                    u32.AppendMenuW(menu, MF_STRING, ID_EXIT, "Exit KuuBot")
                    pt = POINT(); u32.GetCursorPos(ctypes.byref(pt))
                    u32.SetForegroundWindow(hwnd)
                    cmd = u32.TrackPopupMenu(menu, TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                                              pt.x, pt.y, 0, hwnd, None)
                    u32.DestroyMenu(menu)
                    if cmd == ID_EXIT: self._exit_cb()
                return 0
            return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = wp

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = ctypes.cast(wp, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = cls
        u32.RegisterClassExW(ctypes.byref(wc))

        self._hwnd = u32.CreateWindowExW(0, cls, "", 0, 0, 0, 0, 0, None, None, hinst, None)
        self._hicon = _make_icon()

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd; nid.uID = 1
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon; nid.szTip = "KuuBot"
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def stop(self):
        if self._hwnd:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._hwnd; nid.uID = 1
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            ctypes.windll.user32.DestroyWindow(self._hwnd); self._hwnd = None
        if self._hicon:
            ctypes.windll.user32.DestroyIcon(self._hicon); self._hicon = None
