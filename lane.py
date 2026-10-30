from config import strip_height_for

# one tracked note with its press time and hold length
class Note:
    __slots__ = ("press_at", "tail_arrival", "bar_px", "fired")

    # set up a tracked note
    def __init__(self, press_at, tail_arrival, bar_px):
        self.press_at = press_at
        self.tail_arrival = tail_arrival
        self.bar_px = bar_px
        self.fired = False

# tracks one lanes notes and presses its key
class LaneState:
    # set up the lane tracker and key callbacks
    def __init__(self, lane, cfg, key_down, key_up, speed_tracker=None,
                 strip_h=None):
        self.key = lane["key"]
        self.name = lane["name"]
        self.cfg = cfg
        self._down = key_down
        self._up = key_up
        self._speed_tracker = speed_tracker
        self._strip_h = strip_h

        self.down = False
        self.down_since = 0.0
        self.release_at = None
        self.last_release = float("-inf")

        self.queue = []
        self.presses = 0
        self.dropped = 0
        self._tracked = []
        self.capped_bars = 0
        self._last_obs = None

    # ── tracking ────────────────────────────────────────────────────────────
    # match this frames runs to tracked notes and schedule presses
    def observe(self, prof, now):
        c = self.cfg
        speed = float(c.get("fall_speed") or 255)
        lead = c.get("press_lead", 0.05)
        strip_h = self._strip_height(c)
        hit_h = c.get("hit_above", 22) + c.get("hit_below", 0)
        arrow_px = float(c.get("arrow_px", 56))

        dt = 0.0 if self._last_obs is None else (now - self._last_obs)
        self._last_obs = now

        if dt > 0.25:
            self._tracked = []
            fell = 0.0
        else:
            fell = dt * speed

        for tr in self._tracked:
            tr["d"] -= fell
        keep_to = -(strip_h * 0.5)
        self._tracked = [tr for tr in self._tracked if tr["d"] > keep_to]

        tol = max(14.0, fell * 3 + 12)

        nearest_near = min((n for n, _ in prof.runs), default=float("inf"))
        heads_of = dict(enumerate(prof.heads))

        candidates = []
        for ri, (near, _) in enumerate(prof.runs):
            for ti, tr in enumerate(self._tracked):
                err = abs(tr["d"] - near)
                if err < tol:
                    candidates.append((err, ri, ti))
        candidates.sort(key=lambda cand: cand[0])

        run_matched = {}
        matched = set()      # tracked indices already claimed
        for err, ri, ti in candidates:
            if ri in run_matched or ti in matched:
                continue
            run_matched[ri] = ti
            matched.add(ti)

        for ri, (near, far) in enumerate(prof.runs):
            bar = 0.0 if heads_of.get(ri, 1) > 1 else far - near  # stacked arrows arent a hold
            tail = self._tail_arrival(now, far, speed)
            best = run_matched.get(ri)
            if best is not None:
                tr = self._tracked[best]
                self._sample_speed(tr, near, now)
                tr["d"] = near
                if tr["capped"]:
                    holding_this = (self.down
                                    and near <= nearest_near + arrow_px)
                    if far < strip_h - 1:
                        tr["capped"] = False
                        tr["bar"] = bar
                        if tr["note"] is not None:
                            tr["note"].bar_px = bar
                            tr["note"].tail_arrival = tail
                        if holding_this and near <= hit_h:
                            self.release_at = (
                                tail if self.release_at is None
                                else max(self.release_at, tail))
                    elif holding_this and near <= hit_h:
                        lease = now + max(0.03, 4.0 * max(dt, 0.002))
                        if self.release_at is None or self.release_at < lease:
                            self.release_at = lease
                elif bar > tr["bar"]:
                    if (far >= strip_h - 1 and near <= hit_h
                            and bar >= c.get("bar_min_px", 34)):
                        self.capped_bars += 1
                        tr["capped"] = True
                    tr["bar"] = bar
                    if tr["note"] is not None:
                        tr["note"].bar_px = bar
                        tr["note"].tail_arrival = tail
                        if tr["note"].fired:
                            self._extend_hold(tr["note"], tail)
                continue

            if near < 0:
                self._tracked.append({"d": near, "bar": far - near,
                                      "note": None, "capped": False,
                                      "first_seen": now})
                continue

            press_at = now + (near / speed) + lead
            note = Note(press_at, tail, bar)
            self._tracked.append({"d": near, "bar": bar,
                                  "note": note, "capped": False,
                                  "first_seen": now})
            self._insert(note)

    # feed a tracked notes travel into the shared speed estimate
    def _sample_speed(self, tr, near, now):
        tracker = self._speed_tracker
        if tracker is None:
            return
        if "sample_d" not in tr:
            if now - tr["first_seen"] >= tracker.settle_delay:
                tr["sample_d"] = near
                tr["sample_t"] = now
            return
        moved = tr["sample_d"] - near
        if moved >= tracker.min_baseline_px:
            tracker.sample(moved, now - tr["sample_t"])
            tr["sample_d"] = near
            tr["sample_t"] = now

    # usable strip height
    def _strip_height(self, c):
        if self._strip_h is not None:
            return self._strip_h
        return strip_height_for(c)

    # when a holds tail will reach the hit line
    def _tail_arrival(self, now, far, speed):
        head_px = self.cfg.get("head_px", self.cfg.get("bar_min_px", 34))
        lead = self.cfg.get("press_lead", 0.05)
        return now + (far - head_px) / speed + lead

    # how long to hold the key for this bar
    def _hold_for(self, bar_px, press_at, tail_arrival):
        if bar_px < self.cfg.get("bar_min_px", 34):
            return 0.0
        return max(0.0, tail_arrival - press_at)

    # add a note keeping the list time ordered
    def _insert(self, note):
        c = self.cfg
        floor = c.get("tap_press", 0.03) + c.get("repress_gap", 0.006)
        for other in self.queue:
            if abs(other.press_at - note.press_at) < floor * 0.5:
                return                       # same note seen twice
        self.queue.append(note)
        self.queue.sort(key=lambda n: n.press_at)

    # ── key output ──────────────────────────────────────────────────────────
    # advance the lane: observe, then fire due presses and releases
    def update(self, prof, now):
        c = self.cfg
        self.observe(prof, now)

        max_age = c.get("max_press_age", 0.06)
        while self.queue and now - self.queue[0].press_at > max_age:
            self.queue.pop(0)
            self.dropped += 1

        if (self.down and self.release_at is not None and now >= self.release_at
                and now - self.down_since >= c.get("min_press", 0.008)):
            self._release(now)

        # the gap lets the key-up register before the next press
        if (self.queue and now >= self.queue[0].press_at and not self.down
                and now - self.last_release >= c.get("repress_gap", 0.006)):
            self._press(self.queue.pop(0), now)

    # press the key for a note
    def _press(self, note, now):
        self._down(self.key)
        self.down = True
        self.down_since = now
        self.presses += 1
        note.fired = True
        hold = self._hold_for(note.bar_px, now, note.tail_arrival)
        self.release_at = now + (hold if hold > 0
                                 else self.cfg.get("tap_press", 0.03))

    # push a notes release later as its tail grows
    def _extend_hold(self, note, new_tail_arrival):
        if self.down and self.release_at is not None and note.fired:
            hold = self._hold_for(note.bar_px, note.press_at, new_tail_arrival)
            if hold > 0:
                self.release_at = max(self.release_at,
                                      self.down_since + hold)

    # release the held key
    def _release(self, now):
        self._up(self.key)
        self.down = False
        self.last_release = now
        self.release_at = None

    # release the key right now, panic or stop
    def force_release(self):
        if self.down:
            self._up(self.key)
            self.down = False
            self.release_at = None

    # ── debug ───────────────────────────────────────────────────────────────
    # debug string of the lanes current state
    def describe(self, prof):
        state = "##" if prof.hit >= self.cfg.get("hit_fill_ratio", 0.3) else ".."
        kind = ""
        if prof.bar_px:
            kind = "BAR" if prof.bar_px >= self.cfg.get("bar_min_px", 34) else "tap"
        bar_txt = f"{prof.bar_px:.5f}" if prof.bar_px else ""
        return (f"{self.name}={state} q{len(self.queue)} "
                f"{kind}{bar_txt}")
