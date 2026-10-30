import sys
import time
import argparse
import ctypes

import gilcheck  # noqa: F401  (must run before capture.py touches win32gui)
import keyboard

import config
import capture
import ui
from detect import Scanner
from lane import LaneState
from keysender import (KeySender, Output, Recorder, SCAN_CODES, VK_MAP,
                       send_inputs, send_scan)
from grabber import Grabber
from speedtrack import SpeedTracker

# ── The bot ──────────────────────────────────────────────────────────────────
# the live bot: scan the strip, decide, press keys
class Bot:
    # wire up the scanner, lanes and key output
    def __init__(self, cfg, hwnd, debug=False):
        self.cfg = cfg
        self.debug = debug
        cfg["fall_speed"] = config.BASE["fall_speed"]
        self.scanner = Scanner(cfg, hwnd)
        self.out = Recorder() if debug else Output()
        self.speed_tracker = SpeedTracker(cfg)
        self.states = [LaneState(l, cfg, self.out.down, self.out.up,
                                 self.speed_tracker, self.scanner.height)
                       for l in cfg["lanes"]]
        self.running = True
        self.paused = False
        self.sender = None
        self.grabber = None

    # release every held key
    def release_all(self):
        for s in self.states:
            s.force_release()
        events = self.out.take()
        if self.sender:
            self.sender.submit(events)

    # main loop: grab frames and drive the lanes
    def run(self):
        cfg = self.cfg
        keyboard.add_hotkey(cfg["panic_key"], self.stop)
        keyboard.add_hotkey(cfg["toggle_key"], self.toggle)

        ui.header(f"{len(cfg['lanes'])}-LANE  —  "
                  f"{'DEBUG (no keys sent)' if self.debug else 'RUNNING'}")
        print(ui.dim(f"  {self.scanner.region_desc}"))
        print("  " + "   ".join(
            ui.lane_tag(l["name"], l["key"], l.get("hue"))
            for l in cfg["lanes"]))
        print(ui.dim(f"  fall {cfg['fall_speed']:.5f}px/s   "
                     f"lead {cfg['press_lead']*1000:.5f}ms"))
        print(f"  {ui.key('F7')} pause   {ui.key('F8')} quit\n")

        try:
            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00008000)
            k32.SetThreadPriority(k32.GetCurrentThread(), 2)
        except Exception:
            pass

        if not self.debug:
            self.sender = KeySender(send_inputs,
                                    repress_gap=cfg.get("repress_gap", 0.006))
        sc = self.scanner
        self.grabber = Grabber(sc.cap, sc.x0 + sc.dx, sc.y0 + sc.dy)

        frames = 0
        seq = -1
        t_report = time.perf_counter()

        try:
            while self.running:
                if self.paused:
                    self.release_all()
                    time.sleep(0.05)
                    continue

                raw, now, seq = self.grabber.wait_new(seq)
                if raw is None:
                    continue

                profs = self.scanner.profile(raw)
                for st, p in zip(self.states, profs):
                    st.update(p, now)

                if self.out.pending:
                    self.sender.submit(self.out.take())

                frames += 1

                if self.debug and self.out.log:
                    self._show_debug(profs)

                if now - t_report >= 2.0:
                    self._report(frames, now - t_report)
                    frames = 0
                    t_report = now

        except KeyboardInterrupt:
            print("\n  interrupted")
        finally:
            self.release_all()
            self.grabber.stop()
            if self.sender:
                time.sleep(0.05)
                self.sender.stop()
            print(ui.ok("\n  stopped — all keys released"))

    # print what it sees without sending keys
    def _show_debug(self, profs):
        while self.out.log:
            k, what = self.out.log.pop(0)
            state = "  ".join(st.describe(p)
                              for st, p in zip(self.states, profs))
            colour = ui.GREEN if what == "DOWN" else ui.DIM
            print(f"  {colour}{what:4} {k.upper()}{ui.RESET}   "
                  f"{ui.dim(state)}")

    # print the fps and per-lane stats line
    def _report(self, frames, dt):
        rate = frames / dt
        tally = "  ".join(
            f"{ui.lane_colour(l.get('hue'))}{s.name}{ui.RESET}"
            f":{s.presses}" + (ui.red(f"/{s.dropped}") if s.dropped else "")
            for s, l in zip(self.states, self.cfg["lanes"]))
        stalls = self.grabber.stalls
        extra = ui.dim(f"  stalls {stalls}") if stalls else ""
        extra += ui.dim(f"  speed {self.speed_tracker.speed:.5f}px/s")
        capped = sum(s.capped_bars for s in self.states)
        if capped:
            extra += ui.dim(f"  {capped} bar(s) longer than the strip "
                            f"(held by tail-tracking)")
        print(f"  {ui.dim(f'{rate:8.5f} fps')}   {tally}{extra}")

    # stop the bot and release keys
    def stop(self):
        self.running = False

    # pause or resume
    def toggle(self):
        self.paused = not self.paused
        if self.paused:
            self.release_all()
        print(ui.warn("  paused") if self.paused else ui.ok("  resumed"))

# ── Calibration ──────────────────────────────────────────────────────────────
# walk the user through pointing at each receptor arrow
def calibrate(hwnd, mode):
    import win32gui

    cfg = config.load(mode)
    wl, wt, _, _ = capture.window_rect(hwnd)
    dx, dy = capture.client_offset(hwnd)
    cw, ch = capture.client_size(hwnd)

    n_lanes = 2 if mode == "2lane" else 4
    preset = config.LANE_PRESETS[mode]

    ui.header(f"CALIBRATE — {n_lanes} LANES")
    print(f"  Roblox client area {cw}x{ch}\n")
    print("  Point the mouse at the CENTRE of each receptor arrow")
    print("  (the stationary arrows at the bottom) and press ENTER.\n")

    lanes, ys = [], []
    for i in range(n_lanes):
        p = preset[i]
        tag = ui.lane_tag(p["name"], p["key"], p["hue"])
        input(f"  {tag}  arrow #{i + 1} from the left — ENTER when hovering: ")
        sx, sy = win32gui.GetCursorPos()
        cx, cy = sx - wl - dx, sy - wt - dy
        key = input(f"       key for this lane [{p['key']}]: ").strip().lower()
        key = key or p["key"]
        if key not in SCAN_CODES:
            print(ui.red(f"       '{key}' has no scan code — using {p['key']}"))
            key = p["key"]
        print(ui.dim(f"       client x={cx} y={cy}  ->  {key.upper()}"))
        lanes.append({"name": p["name"], "x": cx, "key": key, "hue": p["hue"]})
        ys.append(cy)

    art_top = sum(ys) // len(ys) - 14      # arrows are ~28px tall
    cfg["lanes"] = lanes
    cfg["receptor_y"] = art_top - 4
    cfg["hit_below"] = 0
    cfg["hit_above"] = 22

    xs = sorted(l["x"] for l in lanes)
    gap = min(b - a for a, b in zip(xs, xs[1:])) if len(xs) > 1 else 60
    cfg["lane_half_width"] = max(6, min(30, gap // 2 - 3))
    cfg["_calibrated"] = True

    print()
    ui.field("receptor arrows", f"y{art_top}")
    ui.field("hit zone", f"y{cfg['receptor_y'] - cfg['hit_above']}"
                         f"..y{cfg['receptor_y']}")
    ui.field("lane width", f"{cfg['lane_half_width'] * 2}px")
    for l in lanes:
        ui.field(l["name"], f"x={l['x']}  ->  {l['key'].upper()}",
                 colour=ui.lane_colour(l["hue"]))

    if config.save(cfg, mode):
        print(ui.ok("\n  Saved. Next: Preview to check alignment, then RUN "
                    "— fall speed is tracked live, no BPM needed."))

# save preview.png showing the sampled boxes
def preview(cfg, hwnd):
    from PIL import Image, ImageDraw

    sc = Scanner(cfg, hwnd)
    raw = sc.grab()
    img = Image.frombuffer("RGBA", (sc.width, sc.height), raw,
                           "raw", "BGRA", 0, 1).convert("RGB")
    z = 2
    img = img.resize((img.width * z, img.height * z), Image.NEAREST)
    d = ImageDraw.Draw(img)

    hit_y = sc._hit_r0 * z
    d.rectangle([0, hit_y, img.width - 1, img.height - 1],
                outline=(0, 255, 0), width=2)
    for lane in sc.lanes:
        x0, x1 = lane["b0"] // 4 * z, lane["b1"] // 4 * z
        d.rectangle([x0, 0, x1 - 1, img.height - 1],
                    outline=(255, 60, 60), width=1)
        d.text((x0 + 4, 4), lane["key"].upper(), fill=(255, 255, 0))

    out = config.CONFIG_FILE.parent / "preview.png"
    img.save(out)

    ui.header("PREVIEW")
    print(f"  saved {ui.bold('preview.png')}   {sc.region_desc}")
    print(ui.dim("  red = lane columns    green = hit zone"))
    print(ui.dim("  Each red box should sit on one arrow, with notes falling "
                 "down it.\n"))

    profs = sc.profile(raw)
    for lane, p in zip(sc.lanes, profs):
        bar = (f"{p.bar_px:.5f}px" if p.bar_px else "-")
        kind = ""
        if p.bar_px:
            kind = ("HOLD" if p.bar_px >= cfg.get("bar_min_px", 34) else "tap")
        ui.field(f"{lane['name']} ({lane['key'].upper()})",
                 f"hit {p.hit*100:9.5f}%   runs {len(p.runs)}   "
                 f"at receptor {bar} {kind}")

# shift the press timing earlier or later
def nudge(cfg, delta_ms):
    old = cfg.get("press_lead", 0.0)
    new = max(0.0, round(old + delta_ms / 1000.0, 4))
    cfg["press_lead"] = new
    if config.save(cfg):
        print(f"  press_lead {ui.bold(f'{old*1000:.5f}ms')} -> "
              f"{ui.ok(f'{new*1000:.5f}ms')}  ({delta_ms:+.5f}ms)")

# check key output actually reaches windows
def test_keys(cfg):
    user32 = ctypes.windll.user32
    ui.header("KEY OUTPUT")
    print()

    ok = True
    for lane in cfg["lanes"]:
        k = lane["key"]
        vk = VK_MAP.get(k)
        sent = send_scan(SCAN_CODES[k], False)
        time.sleep(0.04)
        state = bool(user32.GetAsyncKeyState(vk) & 0x8000) if vk else None
        send_scan(SCAN_CODES[k], True)
        time.sleep(0.04)

        if vk is None:
            ui.field(k.upper(), f"sent={sent} (no VK to verify with)")
            continue
        good = sent == 1 and state
        ok = ok and good
        ui.field(k.upper(), ui.ok("registered") if good else ui.red("FAILED"))

    print()
    if ok:
        print(ui.ok("  Key output works.") +
              ui.dim(" If the game ignores the bot, click the Roblox window "
                     "so it has focus."))
    else:
        print(ui.red("  Key output is NOT reaching Windows."))
    return ok

# benchmark capture and detection speed
def bench(cfg, hwnd):
    sc = Scanner(cfg, hwnd)
    raw = sc.grab()
    n = 500
    t = time.perf_counter()
    for _ in range(n):
        sc.profile(raw)
    dt_p = (time.perf_counter() - t) / n

    t = time.perf_counter()
    for _ in range(n):
        sc.grab()
    dt_g = (time.perf_counter() - t) / n

    ui.header("BENCHMARK")
    ui.field("capture", f"{dt_g*1000:.5f} ms")
    ui.field("profile", f"{dt_p*1000:.5f} ms  ({len(sc.lanes)} lanes)")
    ui.field("combined", f"{1/(dt_g+dt_p):.5f} frames/sec")
    print(ui.dim(f"\n  strip {sc.width}x{sc.height}px"))

# menu entry: parse args and run the chosen mode
def main():
    ap = argparse.ArgumentParser(description="Roblox rhythm game bot")
    ap.add_argument("--mode", choices=["2", "4"],
                    help="which lane profile to use")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--nudge", type=float, metavar="MS",
                    help="shift press timing by N ms (+later / -earlier)")
    ap.add_argument("--testkeys", action="store_true")
    ap.add_argument("--bench", action="store_true")
    args = ap.parse_args()

    mode = None
    if args.mode:
        mode = "2lane" if args.mode == "2" else "4lane"
    cfg = config.load(mode)

    if args.testkeys:
        test_keys(cfg)
        return
    if args.nudge is not None:
        nudge(cfg, args.nudge)
        return

    try:
        hwnd = capture.find_roblox_window()
    except capture.WindowNotFound as e:
        print(ui.red(f"\n  {e}\n"))
        sys.exit(1)

    if args.calibrate:
        calibrate(hwnd, mode or cfg.get("_mode", "2lane"))
    elif args.preview:
        preview(cfg, hwnd)
    elif args.bench:
        bench(cfg, hwnd)
    else:
        Bot(cfg, hwnd, debug=args.debug).run()

if __name__ == "__main__":
    main()
