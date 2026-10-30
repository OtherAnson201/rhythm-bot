import sys

import config
from detect import LaneProfile
from lane import LaneState

# read frames, key events and the strip height out of a barlog file
def load(path="barlog.txt"):
    frames = []
    keys = []
    strip = 260
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("# strip="):
                strip = int(line.split("strip=")[1].split()[0])
            if line.startswith("#"):
                continue
            p = line.split()
            if p[0] == "FRAME":
                t = float(p[1])
                lane = int(p[2])
                n = int(p[3])
                i = 4
                runs = []
                if n > 0:
                    for seg in p[4].split(","):
                        a, b = seg.split(":")
                        runs.append((float(a), float(b)))
                    i = 5
                rest = p[i:]
                frames.append((t, lane, runs, int(rest[0]), int(rest[1])))
            elif p[0] == "KEY":
                keys.append((float(p[1]), int(p[2]), p[3]))
    return frames, keys, strip

# replay a logged run through the lane logic and print press counts
def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "barlog.txt"
    frames, recorded, strip = load(path)
    cfg = config.load(None)

    hit_h = cfg.get("hit_above", 22) + cfg.get("hit_below", 0)
    lanes = cfg["lanes"]
    events = []
    cur = [0.0]

    # make a lane tracker whose key callbacks collect events
    def mk(i, lane):
        return LaneState(lane, cfg,
                         lambda k: events.append((i, "DOWN", cur[0])),
                         lambda k: events.append((i, "UP", cur[0])),
                         None, strip)

    states = [mk(i, l) for i, l in enumerate(lanes)]

    for t, lane, runs, _trk, _down in frames:
        cur[0] = t
        prof = LaneProfile()
        prof.runs = runs
        for near, far in runs:
            if near <= hit_h:
                prof.bar_px = far - max(near, 0.0)
                break
        states[lane].update(prof, t)

    print(f"replayed {len(frames)} frames from {path}\n")
    for i, l in enumerate(lanes):
        ev = [e for e in events if e[0] == i]
        holds = []
        open_t = None
        for _, what, t in ev:
            if what == "DOWN":
                open_t = t
            elif open_t is not None:
                holds.append(t - open_t)
                open_t = None
        rec = [e for e in recorded if e[1] == i]
        print(f"  lane {l['name']}: {sum(1 for e in ev if e[1] == 'DOWN')} "
              f"presses (recorded run had "
              f"{sum(1 for e in rec if e[2] == 'DOWN')})")
        if holds:
            print(f"      holds: {[f'{h:.3f}s' for h in holds]}")
            print(f"      longest hold: {max(holds):.3f}s")
        print(f"      capped_bars: {states[i].capped_bars}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
