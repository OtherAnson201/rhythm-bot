import time
import ctypes
import threading
from collections import deque, defaultdict

SendInput = ctypes.windll.user32.SendInput

SCAN_CODES = {
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "y": 0x15,
    "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22, "h": 0x23,
    "j": 0x24, "k": 0x25, "l": 0x26,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30, "n": 0x31,
    "m": 0x32,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07,
    "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "space": 0x39, "left": 0xCB, "right": 0xCD, "up": 0xC8, "down": 0xD0,
}

VK_MAP = {"t": 0x54, "u": 0x55, "i": 0x49, "o": 0x4F, "a": 0x41, "s": 0x53,
          "d": 0x44, "f": 0x46, "w": 0x57, "q": 0x51, "e": 0x45, "r": 0x52,
          "j": 0x4A, "k": 0x4B, "l": 0x4C, "x": 0x58, "c": 0x43, "n": 0x4E,
          "m": 0x4D, "space": 0x20,
          "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

ULONG_PTR = (ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8
             else ctypes.c_ulong)

# windows KEYBDINPUT struct
class _KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR)]

# windows MOUSEINPUT struct
class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]

# windows HARDWAREINPUT struct
class _HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort),
                ("wParamH", ctypes.c_ushort)]

# the union inside windows INPUT
class _InputUnion(ctypes.Union):
    _fields_ = [("ki", _KeyBdInput), ("mi", _MouseInput),
                ("hi", _HardwareInput)]

# windows INPUT struct for SendInput
class _Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _InputUnion)]

INPUT_KEYBOARD = 1
SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(_Input), ctypes.c_int)
SendInput.restype = ctypes.c_uint

_EXPECTED = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
if ctypes.sizeof(_Input) != _EXPECTED:
    raise RuntimeError(
        f"INPUT struct is {ctypes.sizeof(_Input)} bytes, expected {_EXPECTED} — "
        "SendInput would reject every call")

# build an INPUT for a scan code press or release
def make_input(code, keyup):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if keyup else 0)
    if code > 0x7F:
        flags |= KEYEVENTF_EXTENDEDKEY
        code &= 0x7F
    return _Input(INPUT_KEYBOARD,
                  _InputUnion(ki=_KeyBdInput(0, code, flags, 0, 0)))

# send one scan code through SendInput
def send_scan(code, keyup):
    inp = make_input(code, keyup)
    return SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

# send a batch of INPUT structs at once
def send_inputs(inputs):
    n = len(inputs)
    if not n:
        return 0
    arr = (_Input * n)(*inputs)
    return SendInput(n, arr, ctypes.sizeof(_Input))

# buffers real key presses for the sender
class Output:

    # set up the input buffer
    def __init__(self):
        self.pending = []

    # queue a key-down input
    def down(self, key):
        code = SCAN_CODES.get(key.lower())
        if code:
            self.pending.append((make_input(code, False), code, False))

    # queue a key-up input
    def up(self, key):
        code = SCAN_CODES.get(key.lower())
        if code:
            self.pending.append((make_input(code, True), code, True))

    # return and clear the buffered inputs
    def take(self):
        out = self.pending
        self.pending = []
        return out

# fake output for debug mode, records down/up and sends nothing
class Recorder(Output):

    # set up the event log
    def __init__(self):
        super().__init__()
        self.log = []

    # record a down event
    def down(self, key):
        self.log.append((key, "DOWN"))

    # record an up event
    def up(self, key):
        self.log.append((key, "UP"))

# sends queued key events on a background thread, spacing re-presses
class KeySender:

    # start the background key sending thread
    def __init__(self, send, repress_gap=0.006):
        self._send = send
        self._gap = repress_gap
        self._incoming = deque()
        self._perkey = defaultdict(deque)
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._running = True
        self._ready_at = {}

        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="keysender")
        self._thread.start()

    # queue key events to send
    def submit(self, events):
        if not events:
            return
        with self._lock:
            self._incoming.extend(events)
        self._wake.set()

    # drain the queue and fire keys, spacing re-presses apart
    def _loop(self):
        try:
            k32 = ctypes.windll.kernel32
            k32.SetThreadPriority(k32.GetCurrentThread(), 2)  # HIGHEST
        except Exception:
            pass

        while self._running:
            with self._lock:
                while self._incoming:
                    inp, key_id, is_up = self._incoming.popleft()
                    self._perkey[key_id].append((inp, is_up))

            now = time.perf_counter()
            batch = []
            soonest = None

            for key_id, q in self._perkey.items():
                while q:
                    inp, is_up = q[0]
                    if not is_up:
                        ready = self._ready_at.get(key_id, 0.0)
                        if now < ready:
                            if soonest is None or ready < soonest:
                                soonest = ready
                            break
                        self._ready_at.pop(key_id, None)
                    else:
                        self._ready_at[key_id] = now + self._gap
                    q.popleft()
                    batch.append(inp)

            if batch:
                self._send(batch)
                continue

            if soonest is not None:
                delay = soonest - time.perf_counter()
                if delay > 0:
                    time.sleep(min(delay, 0.002))
                continue

            self._wake.wait(0.001)
            self._wake.clear()

    # stop the sender thread
    def stop(self):
        self._running = False
        self._wake.set()
        self._thread.join(timeout=0.5)
