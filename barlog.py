import sys
import time
import argparse

import config
import capture
from detect import Scanner
from lane import LaneState

# capture the lanes and log every run and key event to a file
def main():
    ap = argparse.ArgumentParser(description="log every run and key event")
    ap.add_argument("out", nargs="?", default="barlog.txt")
    ap.add_argument("--mode", choices=["2", "4"])
    args = ap.parse_args()

    mode = None
    if args.mode:
        mode = "2lane" if args.mode == "2" else "4lane"
    cfg = config.load(mode)
    try:
        hwnd = capture.find_roblox_window()
    except capture.WindowNotFound as e:
        print(f"  {e}")
        return 1

    sc = Scanner(cfg, hwnd)
    events = []

    # make a lane tracker whose key callbacks log events
    def mk(idx, lane):
        return LaneState(lane, cfg,
                         lambda k: events.append((time.perf_counter(), idx, "DOWN")),
                         lambda k: events.append((time.perf_counter(), idx, "UP")),
                         None, sc.height)

    states = [mk(i, l) for i, l in enumerate(cfg["lanes"])]
    names = [l["name"] for l in cfg["lanes"]]

    print(f"{len(cfg['lanes'])}-LANE  strip={sc.height}px  hit={sc.hit_h}px  "
          f"row_fill={sc.row_fill}  fall_speed={cfg.get('fall_speed')}")
    print("  " + "  ".join(f"{l['name']}->{l['key'].upper()}({l['hue']})"
                           for l in cfg["lanes"]))
    print(f"  logging EVERY run + lane state to {args.out} — Ctrl+C to stop\n")
    print(f"  {'t':>7}  {'lane':>4} {'runs (near..far)':<46} "
          f"{'trk':>3} {'down':>5}")

    fh = open(args.out, "w", encoding="utf-8", buffering=1)
    fh.write(f"# strip={sc.height} hit={sc.hit_h} "
             f"row_fill={sc.row_fill} fall_speed={cfg.get('fall_speed')} "
             f"press_lead={cfg.get('press_lead')} "
             f"bar_min_px={cfg.get('bar_min_px')}\n")
    fh.write("# FRAME t lane n_runs near:far,... tracked down release_in "
             "bar_px\n")
    fh.write("# KEY t lane DOWN|UP\n")

    fills_saved = {i: 0 for i in range(len(states))}
    n_frames = 0
    n_keys = 0
    longest = {i: 0.0 for i in range(len(states))}
    multi = {i: 0 for i in range(len(states))}
    t0 = time.perf_counter()
    last_print = 0.0
    try:
        while True:
            raw = sc.grab()
            profs = sc.profile(raw)
            now = time.perf_counter()
            rel = now - t0
            for i, (st, p) in enumerate(zip(states, profs)):
                runs = list(p.runs)
                st.update(p, now)
                rin = (st.release_at - now) if st.release_at else None
                rs = ",".join(f"{a:.2f}:{b:.2f}" for a, b in runs)
                fh.write(f"FRAME {rel:.5f} {i} {len(runs)} {rs} "
                         f"{len(st._tracked)} {int(st.down)} "
                         f"{'' if rin is None else f'{rin:.4f}'} "
                         f"{p.bar_px:.2f}\n")
                n_frames += 1
                if runs:
                    longest[i] = max(longest[i], max(b - a for a, b in runs))
                if len(runs) > 1:
                    multi[i] += 1
                if (p.fills is not None and fills_saved[i] < 120
                        and runs and max(b - a for a, b in runs) >= 30):
                    fills_saved[i] += 1
                    fs = ",".join(f"{v:.3f}" for v in p.fills)
                    fh.write(f"FILL {rel:.5f} {i} {fs}\n")
                while events:
                    kt, ki, kw = events.pop(0)
                    fh.write(f"KEY {kt - t0:.5f} {ki} {kw}\n")
                    n_keys += 1
                if runs and rel - last_print > 0.08:
                    last_print = rel
                    txt = " ".join(f"{a:.0f}..{b:.0f}" for a, b in runs[:5])
                    print(f"  {rel:7.2f}  {names[i]:>4} {txt:<46} "
                          f"{len(st._tracked):>3} {str(st.down):>5}")
            time.sleep(0.001)
    except KeyboardInterrupt:
        pass
    finally:
        fh.close()

    print(f"\n  wrote {n_frames} frames and {n_keys} key events to {args.out}")
    for i, name in enumerate(names):
        print(f"  lane {name}: longest run {longest[i]:.0f}px, "
              f"{multi[i]} frames with >1 run")
    return 0

if __name__ == "__main__":
    sys.exit(main())
