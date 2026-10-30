import win32gui
import win32ui
import win32con

# raised when the roblox window isnt found
class WindowNotFound(Exception):
    pass

# find the roblox window handle
def find_roblox_window():
    matches = []

    # enumwindows callback, keep roblox windows
    def cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return
        if win32gui.GetWindowText(h).strip().lower() == "roblox":
            l, t, r, b = win32gui.GetWindowRect(h)
            if (r - l) > 400 and (b - t) > 300:
                matches.append((h, (r - l) * (b - t)))

    win32gui.EnumWindows(cb, None)
    if not matches:
        raise WindowNotFound(
            "Couldn't find the Roblox game window.\n"
            "Make sure Roblox is running and in windowed mode (not minimised)."
        )
    return max(matches, key=lambda m: m[1])[0]

# the windows screen rectangle
def window_rect(hwnd):
    return win32gui.GetWindowRect(hwnd)

# where the client area starts inside the window
def client_offset(hwnd):
    wl, wt, _, _ = win32gui.GetWindowRect(hwnd)
    cl, ct = win32gui.ClientToScreen(hwnd, (0, 0))
    return cl - wl, ct - wt

# client area width and height
def client_size(hwnd):
    l, t, r, b = win32gui.GetClientRect(hwnd)
    return r - l, b - t

# grabs pixels from a window with gdi
class WindowCapture:

    # set up the capture dc for this window
    def __init__(self, hwnd, width, height):
        self.hwnd = hwnd
        self.width = int(width)
        self.height = int(height)
        self._make_dc()

    # make the memory dc and bitmap to blit into
    def _make_dc(self):
        self.wdc = win32gui.GetWindowDC(self.hwnd)
        self.srcdc = win32ui.CreateDCFromHandle(self.wdc)
        self.memdc = self.srcdc.CreateCompatibleDC()
        self.bmp = win32ui.CreateBitmap()
        self.bmp.CreateCompatibleBitmap(self.srcdc, self.width, self.height)
        self.memdc.SelectObject(self.bmp)

    # copy a strip of pixels starting at x,y
    def grab(self, x, y):
        self.memdc.BitBlt((0, 0), (self.width, self.height),
                          self.srcdc, (int(x), int(y)), win32con.SRCCOPY)
        return self.bmp.GetBitmapBits(True)

    # free the gdi handles
    def close(self):
        try:
            self.memdc.DeleteDC()
            self.srcdc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, self.wdc)
            win32gui.DeleteObject(self.bmp.GetHandle())
        except Exception:
            pass

    # free the handles on gc
    def __del__(self):
        self.close()
