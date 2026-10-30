import time
import ctypes
import threading

# grabs frames from a window on a background thread
class Grabber:

    # start the background grab thread and wait for the first frame
    def __init__(self, window_capture, x, y):
        self._cap = window_capture
        self._x = x
        self._y = y
        self._frame = None
        self._stamp = 0.0
        self._seq = 0
        self._lock = threading.Lock()
        self._new = threading.Event()
        self._running = True

        self.stalls = 0          # grabs slower than 2ms

        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="grabber")
        self._thread.start()

        for _ in range(500):
            if self._frame is not None:
                break
            time.sleep(0.002)

    # grab frames nonstop on a high priority thread
    def _loop(self):
        try:
            k32 = ctypes.windll.kernel32
            k32.SetThreadPriority(k32.GetCurrentThread(), 2)  # HIGHEST
        except Exception:
            pass

        while self._running:
            t0 = time.perf_counter()
            try:
                raw = self._cap.grab(self._x, self._y)
            except Exception:
                time.sleep(0.005)
                continue
            now = time.perf_counter()
            if (now - t0) > 0.002:
                self.stalls += 1

            with self._lock:
                self._frame = raw
                self._stamp = now
                self._seq += 1
            self._new.set()

    # block until theres a newer frame than last_seq, or time out
    def wait_new(self, last_seq, timeout=0.02):
        deadline = time.perf_counter() + timeout
        while True:
            with self._lock:
                if self._seq != last_seq and self._frame is not None:
                    return self._frame, self._stamp, self._seq
            if time.perf_counter() >= deadline:
                with self._lock:
                    return self._frame, self._stamp, self._seq
            self._new.wait(0.0005)
            self._new.clear()

    # stop the grab thread
    def stop(self):
        self._running = False
        self._thread.join(timeout=0.5)
