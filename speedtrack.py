# estimates note fall speed live from how far notes move
class SpeedTracker:
    # seed the fall speed estimate from config
    def __init__(self, cfg, min_baseline_px=40, alpha=0.15, cold_samples=7,
                 settle_delay=0.05):
        self.cfg = cfg
        self.min_baseline_px = min_baseline_px
        self.alpha = alpha
        self.cold_samples = cold_samples
        self.settle_delay = settle_delay
        self._estimate = float(cfg.get("fall_speed") or 255)
        self._cold_buffer = []

    # feed one notes travel and nudge the running speed estimate
    def sample(self, moved_px, dt):
        if dt < 0.003 or moved_px < self.min_baseline_px:
            return
        speed = moved_px / dt
        if not (30.0 <= speed <= 4000.0):
            return

        if len(self._cold_buffer) < self.cold_samples:
            self._cold_buffer.append(speed)
            if len(self._cold_buffer) < self.cold_samples:
                return
            s = sorted(self._cold_buffer)
            self._estimate = s[len(s) // 2]
        else:
            max_step = max(40.0, self._estimate * 0.25)
            delta = max(-max_step, min(max_step, speed - self._estimate))
            self._estimate += self.alpha * delta

        self.cfg["fall_speed"] = self._estimate

    # current fall speed estimate
    @property
    def speed(self):
        return self._estimate
