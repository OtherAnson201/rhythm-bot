import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

LANE_PRESETS = {
    "2lane": [
        {"name": "L", "x": 886,  "key": "t", "hue": "cyan"},
        {"name": "R", "x": 1035, "key": "u", "hue": "magenta"},
    ],
    "4lane": [
        {"name": "1", "x": 820,  "key": "x", "hue": "violet"},
        {"name": "2", "x": 900,  "key": "c", "hue": "magenta"},
        {"name": "3", "x": 980,  "key": "n", "hue": "pink"},
        {"name": "4", "x": 1060, "key": "m", "hue": "orange"},
    ],
}

HUES = {
    "cyan":    (60, 201, 189),
    "magenta": (196, 58, 199),
    "violet":  (160, 60, 206),
    "pink":    (236, 67, 122),
    "orange":  (236, 99, 67),
}

BASE = {
    # ── Geometry ────────────────────────────────────────────────────────────
    "receptor_y": 840,
    "lane_half_width": 26,

    "hit_above": 22,
    "hit_below": 0,

    # ── Hold bars ───────────────────────────────────────────────────────────
    "strip_height": None,
    "min_strip_seconds": 0.5,
    "bar_min_px": 34,
    "bar_gap_tol": 6,

    # ── Detection ───────────────────────────────────────────────────────────
    "brightness_min": 110,
    "hue_tol": 50,
    "row_fill": 0.22,
    "hit_fill_ratio": 0.30,

    "seam_drop": 0.55,
    "seam_abs_floor": 0.12,
    "min_note_px": 14,

    # ── Timing ──────────────────────────────────────────────────────────────
    "fall_speed": 255,       # px/sec
    "press_lead": 0.05,

    "min_press": 0.008,
    "tap_press": 0.030,
    "repress_gap": 0.006,
    "max_press_age": 0.060,

    "panic_key": "f8",
    "toggle_key": "f7",
}

# pixel height of the scan strip for this config
def strip_height_for(cfg):
    explicit = cfg.get("strip_height")
    if explicit:
        return int(explicit)
    speed = float(cfg.get("fall_speed") or 255)
    seconds = cfg.get("min_strip_seconds", 0.5)
    return max(150, int(speed * seconds))

# built-in defaults for a lane mode
def _profile(mode):
    p = json.loads(json.dumps(BASE))
    p["lanes"] = json.loads(json.dumps(LANE_PRESETS[mode]))
    if mode == "4lane":
        p["lane_half_width"] = 18
    return p

# the default config document
def defaults():
    return {
        "active": "2lane",
        "profiles": {"2lane": _profile("2lane"), "4lane": _profile("4lane")},
    }

# read the raw config json, or defaults
def load_doc():
    doc = defaults()
    if not CONFIG_FILE.exists():
        return doc
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[config] couldn't read config.json ({e}) — using defaults")
        return doc
    if not isinstance(saved, dict):
        return doc

    doc["active"] = saved.get("active", doc["active"])
    for mode, prof in saved.get("profiles", {}).items():
        base = doc["profiles"].get(mode) or _profile("2lane")
        if isinstance(prof, dict):
            base.update(prof)
        doc["profiles"][mode] = base
    return doc

# load the active or given lane modes config
def load(mode=None):
    doc = load_doc()
    mode = mode or doc.get("active", "2lane")
    cfg = doc["profiles"].get(mode) or _profile(mode)
    cfg["_mode"] = mode

    explicit = cfg.get("strip_height")
    if explicit and explicit < strip_height_for({**cfg, "strip_height": None}):
        cfg["strip_height"] = None

    return cfg

# write the config back to json
def save(cfg, mode=None):
    mode = mode or cfg.get("_mode") or "2lane"
    cfg = {k: v for k, v in cfg.items() if k != "_mode"}

    cfg["fall_speed"] = BASE["fall_speed"]

    notes = repair(cfg)
    hard = fatal(cfg)
    if hard:
        print("[config] NOT saved — these values cannot be right:")
        for p in hard:
            print(f"  ! {p}")
        return False

    doc = load_doc()
    doc["profiles"][mode] = cfg
    doc["active"] = mode

    if CONFIG_FILE.exists():
        try:
            CONFIG_FILE.with_suffix(".prev.json").write_text(
                CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass

    CONFIG_FILE.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    for n in notes:
        print(f"  [config] adjusted: {n}")
    print(f"[config] saved profile '{mode}' -> {CONFIG_FILE.name}")
    return True

# list the values that are too wrong to save
def fatal(cfg):
    bad = []
    ry = cfg.get("receptor_y", 0)
    if not (40 <= ry <= 2000):
        bad.append(f"receptor_y={ry} is outside any plausible screen")
    if not cfg.get("lanes"):
        bad.append("no lanes defined")
    for lane in cfg.get("lanes", []):
        x = lane.get("x", -1)
        if not (0 <= x <= 4000):
            bad.append(f"lane {lane.get('name')} x={x} is off screen")
    return bad

# fill in missing or bad config fields
def repair(cfg):
    fixed = []
    ry = int(cfg.get("receptor_y", 840))

    if ry - int(cfg.get("hit_above", 22)) < 0:
        cfg["hit_above"] = max(4, ry - 1)
        fixed.append(f"hit_above clamped to {cfg['hit_above']}")

    lead = cfg.get("press_lead", 0.0)
    if not (0 <= lead <= 0.6):
        cfg["press_lead"] = 0.05
        fixed.append(f"press_lead {lead*1000:.5f}ms -> 50ms")

    lanes = sorted(cfg.get("lanes", []), key=lambda l: l.get("x", 0))
    if len(lanes) > 1:
        gap = min(b["x"] - a["x"] for a, b in zip(lanes, lanes[1:]))
        hw = cfg.get("lane_half_width", 26)
        limit = max(5, gap // 2 - 2)
        if hw > limit:
            cfg["lane_half_width"] = limit
            fixed.append(f"lane_half_width {hw} -> {limit} (lanes {gap}px apart)")

    return fixed

# switch the active lane mode and save
def set_active(mode):
    doc = load_doc()
    doc["active"] = mode
    CONFIG_FILE.write_text(json.dumps(doc, indent=2), encoding="utf-8")
