import sys
import random

import speedtrack
from config import BASE, HUES
from detect import LaneProfile, Scanner
from lane import LaneState

FPS = 1000.0          # simulated scan rate
SPEED = 255.0         # px/sec fall speed

# a minimal config for the tests
def make_cfg(**over):
    c = dict(BASE)
    c["fall_speed"] = SPEED
    c["press_lead"] = 0.0
    c.update(over)
    return c

# fake key output that records presses and holds
class Recorder:
    # set up the event log
    def __init__(self):
        self.events = []
        self.t = 0.0

    # record a down event
    def down(self, k):
        self.events.append((round(self.t, 4), k, "DOWN"))

    # record an up event
    def up(self, k):
        self.events.append((round(self.t, 4), k, "UP"))

    # the recorded press times
    @property
    def presses(self):
        return [e for e in self.events if e[2] == "DOWN"]

    # the recorded hold durations
    def holds(self):
        out, open_at = [], {}
        for t, k, what in self.events:
            if what == "DOWN":
                open_at[k] = t
            elif k in open_at:
                out.append((k, round(t - open_at.pop(k), 4)))
        return out

# feed scripted note runs through a lane and collect its output
def simulate(notes, cfg=None, duration=3.0, strip=260, hit_h=22,
             fps=FPS, drop=0.0, jitter=0.0, seed=7):
    rng = random.Random(seed)
    cfg = cfg or make_cfg()
    rec = Recorder()
    st = LaneState({"name": "L", "key": "t"}, cfg, rec.down, rec.up)

    steps = int(duration * fps)
    for i in range(steps):
        if drop and rng.random() < drop:
            continue                      # this frame never arrived
        t = i / fps + (rng.uniform(-jitter, jitter) if jitter else 0.0)
        rec.t = t
        prof = LaneProfile()
        runs = []
        for arrive, bar_px in notes:
            near = (arrive - t) * SPEED
            far = near + bar_px
            if far < 0 or near > strip:
                continue
            runs.append((max(near, -hit_h), min(far, strip)))
        prof.runs = sorted(runs)
        for near, far in prof.runs:
            if near <= hit_h:
                prof.bar_px = int(far - near)
                break
        prof.hit = 1.0 if any(n <= hit_h and f >= 0 for n, f in prof.runs) else 0.0
        st.update(prof, t)
    return rec, st

# ── checks ───────────────────────────────────────────────────────────────────
RESULTS = []

# assert the recorded presses match whats expected
def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}")
    if detail and not ok:
        print(f"         {detail}")

# a single tap presses once
def test_single_tap():
    rec, _ = simulate([(1.0, 20)])
    n = len(rec.presses)
    check("single tap -> exactly one press", n == 1, f"got {n}")

# a tap fires at the right moment
def test_tap_timing():
    rec, _ = simulate([(1.0, 20)])
    if rec.presses:
        t = rec.presses[0][0]
        check("tap presses within 20ms of arrival", abs(t - 1.0) <= 0.02,
              f"pressed at {t:.3f}s, note arrived at 1.000s")
    else:
        check("tap presses within 20ms of arrival", False, "no press at all")

# overlapping notes each get pressed
def test_overlapping_notes():
    rec, _ = simulate([(1.0, 20), (1.157, 20)])
    n = len(rec.presses)
    check("two overlapping notes -> two presses", n == 2, f"got {n}")

# two touching notes arent merged
def test_touching_notes():
    rec, _ = simulate([(1.0, 20), (1.08, 20)])
    n = len(rec.presses)
    check("back-to-back notes -> two presses", n == 2, f"got {n}")

# note matching doesnt depend on order
def test_matching_is_order_independent():
    cfg = make_cfg(fall_speed=400.0, strip_height=500, press_lead=0.0)
    rec = Recorder()
    st = LaneState({"name": "L", "key": "t"}, cfg, rec.down, rec.up,
                   strip_h=500)

    prof = LaneProfile()
    prof.runs = [(100, 118), (112, 130)]
    rec.t = 1.000
    st.update(prof, 1.000)
    before = sorted(tr["d"] for tr in st._tracked)

    prof2 = LaneProfile()
    prof2.runs = [(111, 129), (101, 119)]
    st.update(prof2, 1.000)
    after = sorted(tr["d"] for tr in st._tracked)

    ok = len(after) == 2 and all(abs(a - b) < 3 for a, b in zip(before, after))
    check("reordered close runs still pair with the correct tracked note",
          ok, f"before={before} after={after}")

# a fast burst of notes all register
def test_dense_burst():
    notes = [(1.0 + i * 0.1, 18) for i in range(10)]
    rec, _ = simulate(notes, duration=3.0)
    n = len(rec.presses)
    check("10-note burst -> 10 presses", n == 10, f"got {n}")

# a hold bars length is measured right
def test_hold_bar_length():
    bar = 200
    rec, _ = simulate([(1.0, bar)], duration=4.0)
    holds = rec.holds()
    if not holds:
        check("hold bar keeps the key down for its length", False, "no press")
        return
    _, held = holds[0]
    want = (bar - BASE["bar_min_px"]) / SPEED
    check("hold bar keeps the key down for its length",
          abs(held - want) <= 0.05, f"held {held:.3f}s, expected ~{want:.3f}s")

# a long hold isnt mistaken for a tap
def test_hold_not_treated_as_tap():
    rec, _ = simulate([(1.0, 220)], duration=4.0)
    holds = rec.holds()
    ok = holds and holds[0][1] > 0.3
    check("long bar is not released as a tap", bool(ok),
          f"held {holds[0][1]:.3f}s" if holds else "no press")

# a short tap isnt mistaken for a hold
def test_tap_not_treated_as_hold():
    rec, _ = simulate([(1.0, 20)], duration=3.0)
    holds = rec.holds()
    ok = holds and holds[0][1] <= 0.08
    check("short arrow is released quickly (tap)", bool(ok),
          f"held {holds[0][1]:.3f}s" if holds else "no press")

# a hold then a tap both fire
def test_hold_then_tap():
    rec, _ = simulate([(1.0, 180), (2.0, 20)], duration=4.0)
    n = len(rec.presses)
    check("hold then tap -> two separate presses", n == 2, f"got {n}")

# queued notes dont cut a hold short
def test_hold_not_cut_short_by_queued_notes():
    bar = 220
    notes = [(1.0, bar)] + [(1.9 + i * 0.05, 18) for i in range(6)]
    rec, _ = simulate(notes, duration=5.0)
    holds = rec.holds()
    assert_hold = next((h for k, h in holds if h > 0.3), None)
    check("a hold with many notes queued behind it is still held its full length",
          assert_hold is not None and assert_hold > 0.3,
          f"holds recorded: {holds}")

# how far a measured hold is off from expected
def _hold_error(bar_px, press_lead, strip=400, speed=SPEED, hit_h=22,
                dur=5.0, arrival=2.0):
    cfg = make_cfg(press_lead=press_lead, strip_height=strip,
                   fall_speed=speed)
    rec = Recorder()
    st = LaneState({"name": "L", "key": "t"}, cfg, rec.down, rec.up)
    fps = 500.0
    for i in range(int(dur * fps)):
        t = i / fps
        rec.t = t
        near_head = (arrival - t) * speed
        far = near_head + bar_px
        prof = LaneProfile()
        if not (far < 0 or near_head > strip):
            n = max(near_head, -hit_h)
            f = min(far, strip)
            prof.runs = [(n, f)]
            prof.bar_px = int(f - n) if n <= hit_h else 0
        st.update(prof, t)
    holds = rec.holds()
    if not holds:
        return None, None, None
    held = holds[0][1]
    remaining = (bar_px - BASE["bar_min_px"]) / speed
    expected = remaining if remaining > 0 else BASE["tap_press"]
    return held, expected, abs(held - expected) * 1000

# hold timing with a short press lead
def test_hold_timing_short_lead():
    held, expected, err_ms = _hold_error(bar_px=300, press_lead=0.02)
    check("hold timing accurate with a short press_lead", err_ms < 15,
          f"held {held:.5f}s, expected {expected:.5f}s ({err_ms:.5f}ms off)")

# hold timing with a large press lead
def test_hold_timing_large_lead():
    held, expected, err_ms = _hold_error(bar_px=200, press_lead=0.15)
    check("hold timing accurate with a large press_lead", err_ms < 15,
          f"held {held:.5f}s, expected {expected:.5f}s ({err_ms:.5f}ms off)")

# hold timing across different bar lengths
def test_hold_timing_various_lengths():
    worst = 0.0
    for bar_px in (60, 120, 200, 300, 380):
        for lead in (0.02, 0.08, 0.188):
            held, expected, err_ms = _hold_error(bar_px, lead)
            if err_ms is None:
                check(f"hold fires for bar={bar_px}px lead={lead}", False,
                      "no press")
                return
            worst = max(worst, err_ms)
    check("hold timing stays accurate across bar lengths and lead values",
          worst < 15, f"worst error {worst:.5f}ms")

# nothing presses when theres no note
def test_no_phantom_presses():
    rec, _ = simulate([], duration=2.0)
    n = len(rec.presses)
    check("empty lane -> no presses", n == 0, f"got {n}")

# the key lifts between two presses
def test_key_released_between_presses():
    notes = [(1.0 + i * 0.15, 18) for i in range(6)]
    rec, _ = simulate(notes, duration=3.0)
    seq = [e[2] for e in rec.events]
    ok = all(seq[i] != seq[i + 1] for i in range(len(seq) - 1))
    check("DOWN/UP always alternate", ok, "".join("D" if s == "DOWN" else "U"
                                                  for s in seq))

# re-presses keep the minimum gap
def test_repress_gap_respected():
    notes = [(1.0 + i * 0.12, 18) for i in range(6)]
    rec, _ = simulate(notes, duration=3.0)
    gap = BASE["repress_gap"]
    worst = None
    for i in range(len(rec.events) - 1):
        t0, _, a = rec.events[i]
        t1, _, b = rec.events[i + 1]
        if a == "UP" and b == "DOWN":
            d = t1 - t0
            if worst is None or d < worst:
                worst = d
    ok = worst is None or worst >= gap - 0.002
    check("gap between release and next press", ok,
          f"smallest gap {worst*1000:.5f}ms, need {gap*1000:.5f}ms"
          if worst else "")

# still works at a low frame rate
def test_low_frame_rate():
    notes = [(1.0 + i * 0.15, 18) for i in range(8)]
    rec, _ = simulate(notes, duration=3.0, fps=200.0)
    n = len(rec.presses)
    check("8 notes at 200fps capture -> 8 presses", n == 8, f"got {n}")

# survives dropped frames
def test_dropped_frames():
    notes = [(1.0 + i * 0.12, 18) for i in range(10)]
    rec, _ = simulate(notes, duration=3.5, fps=400.0, drop=0.30)
    n = len(rec.presses)
    check("10 notes with 30% frames dropped -> 10 presses", n == 10, f"got {n}")

# survives jittery frame timing
def test_timing_jitter():
    notes = [(1.0 + i * 0.13, 18) for i in range(8)]
    rec, _ = simulate(notes, duration=3.0, fps=500.0, jitter=0.002)
    n = len(rec.presses)
    check("8 notes with 2ms timing jitter -> 8 presses", n == 8, f"got {n}")

# keeps up under heavy load
def test_heavy_load():
    notes = [(1.0 + i * 0.11, 18) for i in range(12)]
    rec, _ = simulate(notes, duration=4.0, fps=250.0, drop=0.20, jitter=0.002)
    n = len(rec.presses)
    check("12 notes under heavy load -> 12 presses", n == 12, f"got {n}")

# a hold survives dropped frames
def test_hold_survives_dropped_frames():
    rec, _ = simulate([(1.0, 200)], duration=4.0, fps=400.0, drop=0.25)
    holds = rec.holds()
    want = (200 - BASE["bar_min_px"]) / SPEED
    ok = holds and abs(holds[0][1] - want) <= 0.06
    check("hold length survives dropped frames", bool(ok),
          f"held {holds[0][1]:.3f}s, expected ~{want:.3f}s" if holds
          else "no press")

# a too-old pending press is dropped
def test_stale_press_dropped():
    cfg = make_cfg(press_lead=0.0)
    rec, st = simulate([(1.0, 18)], cfg=cfg, duration=3.0)
    late = [t for t, _, w in rec.events if w == "DOWN" and t > 1.0 + 0.06]
    check("no press fires past max_press_age", not late, f"late presses: {late}")

# ── pixel-level checks ───────────────────────────────────────────────────────
# a scanner with no window, the tests draw its frames by hand
def _fake_scanner(strip=200, hit_h=22):
    return Scanner(make_cfg(lanes=[{"name": "L", "x": 30, "key": "t", "hue": "cyan"},
                                   {"name": "R", "x": 110, "key": "u", "hue": "magenta"}],
                            lane_half_width=20, strip_height=strip,
                            hit_above=hit_h, hit_below=0, receptor_y=strip))

# draw a note block into the fake frame
def _draw(sc, shapes):
    W, H = sc.width, sc.height
    buf = bytearray(W * H * 4)
    for cx, top, h, rgb, pointed in shapes:
        r, g, b = rgb
        for y in range(max(0, top), min(H, top + h)):
            if pointed:
                f = (y - top) / max(1, h - 1)
                half = max(2, int(4 + 11 * (1 - abs(f - 0.45) * 2)))
            else:
                half = 15
            for x in range(max(0, cx - half), min(W, cx + half)):
                o = (y * W + x) * 4
                buf[o], buf[o + 1], buf[o + 2], buf[o + 3] = b, g, r, 255
    return bytes(buf)

# stacked arrows split into separate notes
def test_stacked_arrows_split():
    sc = _fake_scanner()
    H = sc.height
    shapes = []
    for i in range(4):
        t = H - 30 - i * 30
        shapes.append((30, t, 26, HUES["cyan"], True))
        shapes.append((110, t, 26, HUES["magenta"], True))
    profs = sc.profile(_draw(sc, shapes))
    counts = [len(p.runs) for p in profs]
    check("4 stacked arrows read as 4 separate notes", counts == [4, 4],
          f"got {counts}")

# a solid hold bar isnt split
def test_hold_bar_not_split():
    sc = _fake_scanner()
    H = sc.height
    profs = sc.profile(_draw(sc, [(30, H - 150, 150, HUES["cyan"], False),
                                  (110, H - 150, 150, HUES["magenta"], False)]))
    counts = [len(p.runs) for p in profs]
    bars = [p.bar_px for p in profs]
    check("a 150px hold bar stays one note", counts == [1, 1],
          f"got {counts} runs, bars {bars}")

# draw a hold bar into the fake frame
def _draw_hold(sc, cx, head_top, head_h, bar_h, rgb, bar_half=6):
    W, H = sc.width, sc.height
    buf = bytearray(W * H * 4)
    r, g, b = rgb

    # render the fake frame to pixels
    def paint(x0, x1, y0, y1):
        for y in range(max(0, y0), min(H, y1)):
            for x in range(max(0, x0), min(W, x1)):
                o = (y * W + x) * 4
                buf[o], buf[o + 1], buf[o + 2], buf[o + 3] = b, g, r, 255

    for y in range(max(0, head_top), min(H, head_top + head_h)):
        f = (y - head_top) / max(1, head_h - 1)
        half = max(2, int(4 + 11 * (1 - abs(f - 0.45) * 2)))
        paint(cx - half, cx + half, y, y + 1)
    paint(cx - bar_half, cx + bar_half, head_top - bar_h, head_top)
    return bytes(buf)

# a hold whose head is wider than its tail isnt split
def test_hold_bar_head_wider_than_tail_not_split():
    sc = _fake_scanner(strip=300)
    H = sc.height
    raw = _draw_hold(sc, 30, H - 30, 26, 150, HUES["cyan"], bar_half=6)
    profs = sc.profile(raw)
    p = profs[0]
    check("wide-head, narrow-bar hold stays one run",
          len(p.runs) == 1, f"got {len(p.runs)} runs: {p.runs}")
    check("measured bar length matches the true ~176px bar",
          p.bar_px >= 150, f"bar_px={p.bar_px}, expected >= 150")

# one lanes color doesnt leak into another
def test_lane_colour_isolation():
    sc = _fake_scanner()
    H = sc.height
    profs = sc.profile(_draw(sc, [(30, H - 60, 40, HUES["magenta"], True)]))
    check("cyan lane ignores a magenta arrow", profs[0].hit == 0.0,
          f"cyan lane read hit={profs[0].hit:.2f}")

# the background isnt read as notes
def test_background_ignored():
    sc = _fake_scanner()
    H = sc.height
    profs = sc.profile(_draw(sc, [(30, H - 80, 60, (120, 70, 45), False),
                                  (110, H - 80, 60, (255, 255, 255), False)]))
    ok = profs[0].hit == 0.0 and profs[1].hit == 0.0
    check("wood background and white flash are not notes", ok,
          f"hits {[round(p.hit, 2) for p in profs]}")

# build a scanner profile from drawn notes
def _render_notes(st, rec, notes, t0, t1, speed, fps=500.0, hit_h=22, strip=500):
    for i in range(int((t1 - t0) * fps)):
        t = t0 + i / fps
        rec.t = t
        runs = []
        for arrival, bar in notes:
            near_head = (arrival - t) * speed
            far = near_head + bar
            if far < 0 or near_head > strip:
                continue
            n = max(near_head, -hit_h)
            f = min(far, strip)
            runs.append((n, f))
        prof = LaneProfile()
        prof.runs = sorted(runs)
        for n, f in prof.runs:
            if n <= hit_h:
                prof.bar_px = int(f - n)
                break
        st.update(prof, t)

# speed tracker follows a tempo increase
def test_speed_tracker_follows_tempo_change():
    cfg = make_cfg(strip_height=500, fall_speed=255.0)
    tracker = speedtrack.SpeedTracker(cfg)
    rec = Recorder()
    st = LaneState({"name": "L", "key": "t"}, cfg, rec.down, rec.up,
                   tracker, strip_h=500)

    _render_notes(st, rec, [(1.0 + i * 0.4, 20) for i in range(6)], 0.0, 3.5, 255.0)
    check("speed estimate stays put when the song matches calibration",
          abs(tracker.speed - 255.0) < 5.0, f"estimate={tracker.speed:.5f}px/s")

    _render_notes(st, rec, [(4.0 + i * 0.3, 20) for i in range(10)], 3.5, 8.0, 450.0)
    check("speed estimate follows a mid-song tempo increase",
          abs(tracker.speed - 450.0) < 20.0,
          f"estimate={tracker.speed:.5f}px/s, true=450px/s")

    check("every note still presses exactly once through the tempo change",
          len(rec.presses) == 16, f"got {len(rec.presses)} presses")

# speed tracker follows a tempo drop
def test_speed_tracker_follows_tempo_decrease():
    cfg = make_cfg(strip_height=500, fall_speed=400.0)
    tracker = speedtrack.SpeedTracker(cfg)
    rec = Recorder()
    st = LaneState({"name": "L", "key": "t"}, cfg, rec.down, rec.up,
                   tracker, strip_h=500)

    _render_notes(st, rec, [(1.0 + i * 0.3, 20) for i in range(8)], 0.0, 3.5, 400.0)
    _render_notes(st, rec, [(4.0 + i * 0.5, 20) for i in range(6)], 3.5, 8.0, 200.0)
    check("speed estimate follows a mid-song tempo decrease",
          abs(tracker.speed - 200.0) < 20.0,
          f"estimate={tracker.speed:.5f}px/s, true=200px/s")

# cold start snaps to the first real sample
def test_speed_tracker_cold_start_snaps_fast():
    cfg = {"fall_speed": 255.0}
    tracker = speedtrack.SpeedTracker(cfg)
    for _ in range(tracker.cold_samples):
        tracker.sample(45.0, 0.05)   # clean 900px/s samples
    check("the estimate becomes usable within the cold-start window",
          abs(tracker.speed - 900.0) < 5.0,
          f"estimate={tracker.speed:.5f}px/s after {tracker.cold_samples} "
          f"samples, true=900px/s")

# cold start ignores a single bad sample
def test_speed_tracker_cold_start_resists_one_bad_sample():
    cfg = {"fall_speed": 255.0}
    tracker = speedtrack.SpeedTracker(cfg)
    true_speed = 700.0
    samples = [true_speed] * (tracker.cold_samples - 1) + [true_speed * 3]
    for speed in samples:
        tracker.sample(speed * 0.1, 0.1)
    check("one bad sample in the cold window doesn't poison the first estimate",
          abs(tracker.speed - true_speed) < 40.0,
          f"estimate={tracker.speed:.5f}px/s, true={true_speed:.5f}px/s")

# warmed up it resists one bad sample
def test_speed_tracker_warm_resists_one_bad_sample():
    cfg = {"fall_speed": 255.0}
    tracker = speedtrack.SpeedTracker(cfg)
    for _ in range(10):
        tracker.sample(45.0, 0.15)   # 300px/s, well past cold_samples
    before = tracker.speed
    tracker.sample(45.0, 0.03)       # one bad-match outlier: 1500px/s
    check("a warm estimate is not yanked by a single outlier sample",
          abs(tracker.speed - before) < 60.0,
          f"before={before:.5f}px/s after={tracker.speed:.5f}px/s")

# spawn animation jitter doesnt fool the speed tracker
def test_speed_survives_spawn_animation_jitter():
    true_speed = 400.0
    cfg = dict(BASE)
    cfg["fall_speed"] = true_speed
    cfg["strip_height"] = 350
    tracker = speedtrack.SpeedTracker(cfg)
    rec = Recorder()
    st = LaneState({"name": "L", "key": "t"}, cfg, rec.down, rec.up,
                   tracker, strip_h=350)

    rng = random.Random(9)
    notes = [(1.0 + i * 0.3, 18) for i in range(10)]
    fps, hit_h, strip = 1000.0, 22, 350
    speed_log = []
    for i in range(int(4.5 * fps)):
        t = i / fps
        runs = []
        for arrival, bar in notes:
            near_head = (arrival - t) * true_speed
            far = near_head + bar
            if far < 0 or near_head > strip:
                continue
            if strip - near_head < 15:
                near_head += rng.uniform(-25, 25)
            n = max(near_head, -hit_h)
            f = min(far, strip)
            if f <= n:
                continue
            runs.append((n, f))
        prof = LaneProfile()
        prof.runs = sorted(runs)
        for n, f in prof.runs:
            if n <= hit_h:
                prof.bar_px = int(f - n)
                break
        st.update(prof, t)
        speed_log.append(tracker.speed)

    spread = max(speed_log) - min(speed_log)
    check("spawn-animation jitter does not move the live speed estimate",
          spread < 20.0,
          f"speed ranged {min(speed_log):.5f}..{max(speed_log):.5f}px/s "
          f"(true={true_speed:.5f}px/s)")

# run all the tests and print pass/fail
def main():
    print("\nrhythm bot — logic checks")
    print("=" * 52)
    print("\nBasic detection")
    test_single_tap()
    test_tap_timing()
    test_no_phantom_presses()

    print("\nOverlapping and dense notes")
    test_overlapping_notes()
    test_touching_notes()
    test_matching_is_order_independent()
    test_dense_burst()
    test_key_released_between_presses()
    test_repress_gap_respected()

    print("\nHold bars")
    test_hold_bar_length()
    test_hold_not_treated_as_tap()
    test_tap_not_treated_as_hold()
    test_hold_then_tap()
    test_hold_not_cut_short_by_queued_notes()
    test_hold_timing_short_lead()
    test_hold_timing_large_lead()
    test_hold_timing_various_lengths()

    print("\nUnder load (dropped frames, jitter, low fps)")
    test_low_frame_rate()
    test_dropped_frames()
    test_timing_jitter()
    test_heavy_load()
    test_hold_survives_dropped_frames()

    print("\nPixel detection (synthetic frames)")
    test_stacked_arrows_split()
    test_hold_bar_not_split()
    test_hold_bar_head_wider_than_tail_not_split()
    test_lane_colour_isolation()
    test_background_ignored()

    print("\nTiming safety")
    test_stale_press_dropped()

    print("\nLive tempo-change tracking")
    test_speed_tracker_follows_tempo_change()
    test_speed_tracker_follows_tempo_decrease()
    test_speed_tracker_cold_start_snaps_fast()
    test_speed_tracker_cold_start_resists_one_bad_sample()
    test_speed_tracker_warm_resists_one_bad_sample()
    test_speed_survives_spawn_animation_jitter()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("\n" + "=" * 52)
    print(f"  {passed}/{total} passed")
    if passed != total:
        print("\n  Failing checks:")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"    - {name}: {detail}")
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
