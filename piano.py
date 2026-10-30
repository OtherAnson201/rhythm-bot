import time
import random
import argparse
import threading
from pathlib import Path

import keyboard

from keysender import SCAN_CODES, make_input, send_inputs

SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
}
SHIFT_SCAN = 0x2A

_ROWS = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")
_POS = {ch: (r, c) for r, row in enumerate(_ROWS) for c, ch in enumerate(row)}

# how many keys apart two note letters sit on the keyboard
def key_distance(a, b):
    pa = _POS.get(a.lower())
    pb = _POS.get(b.lower())
    if pa is None or pb is None:
        return None
    return abs(pa[0] - pb[0]) + abs(pa[1] - pb[1])

# scan code for one character and whether it needs shift
def key_events(ch):
    if ch in SHIFTED:
        return SCAN_CODES.get(SHIFTED[ch]), True
    if ch.isupper():
        return SCAN_CODES.get(ch.lower()), True
    return SCAN_CODES.get(ch), False

# press several keys together for one beat
def press_chord(chars, hold=0.03):
    codes = []
    need_shift = False
    for ch in chars:
        code, shifted = key_events(ch)
        if code is None:
            continue
        codes.append(code)
        need_shift = need_shift or shifted
    if not codes:
        return

    down = []
    if need_shift:
        down.append(make_input(SHIFT_SCAN, False))
    down += [make_input(c, False) for c in codes]
    send_inputs(down)

    time.sleep(hold)

    up = [make_input(c, True) for c in codes]
    if need_shift:
        up.append(make_input(SHIFT_SCAN, True))
    send_inputs(up)

# parse a sheet string into timed note events
def parse(sheet):
    events = []
    i = 0
    n = len(sheet)
    while i < n:
        ch = sheet[i]
        if ch in " \t\r\n":
            i += 1
        elif ch == "[":
            j = sheet.find("]", i)
            if j == -1:
                break
            events.append(("chord", [c for c in sheet[i + 1:j] if not c.isspace()]))
            i = j + 1
        elif ch == "{":
            j = sheet.find("}", i)
            if j == -1:
                break
            events.append(("fast", [c for c in sheet[i + 1:j] if not c.isspace()]))
            i = j + 1
        elif ch == "-":
            j = i
            while j < n and sheet[j] == "-":
                j += 1
            events.append(("rest", j - i))
            i = j
        else:
            events.append(("chord", [ch]))
            i += 1
    return events

# play the parsed events with timing
def play(events, step=0.25, rest=0.5, hold=0.03, fast_div=4.0,
         near=0.25, near_dist=2, jitter=0.12, floor=0.25):
    stop = threading.Event()
    keyboard.add_hotkey("f8", stop.set)

    print(f"Playing {len(events)} events — {step*1000:.0f}ms single, "
          f"{rest*1000:.0f}ms chord/pause  (F8 to stop)")
    print("Starting in 5s — focus the piano window now.")
    for s in range(5, 0, -1):
        if stop.is_set():
            return
        print(f"  {s}...", end="\r", flush=True)
        time.sleep(1)
    print("  playing.        ")

    played = 0
    for idx, (kind, payload) in enumerate(events):
        if stop.is_set():
            break
        nxt = None
        if idx + 1 < len(events):
            nkind, npayload = events[idx + 1]
            if nkind in ("chord", "fast") and npayload:
                nxt = npayload[0]
        if kind == "rest":
            time.sleep(rest * payload)
        elif kind == "chord":
            press_chord(payload, hold)
            played += 1
            if len(payload) == 1:
                wait = step
                d = key_distance(payload[0], nxt) if nxt else None
                if d is not None and d <= near_dist:
                    wait = near
            else:
                wait = rest
            if jitter:
                wait *= random.uniform(1.0, 1.0 + jitter)
            wait = max(wait, floor)
            time.sleep(max(0.0, wait - hold))
        elif kind == "fast":
            fast_step = step / fast_div
            for ch in payload:
                if stop.is_set():
                    break
                w = fast_step
                if jitter:
                    w *= random.uniform(1.0, 1.0 + jitter)
                w = max(w, floor)
                h = min(hold, w * 0.5)
                press_chord([ch], h)
                played += 1
                time.sleep(max(0.0, w - h))

    print(f"Done — {played} notes/chords played.")

# strip junk out of pasted sheet text
def clean(text):
    lines = []
    for ln in text.splitlines():
        low = ln.strip().lower()
        if not low:
            continue
        if low.startswith("how to play"):
            continue
        if "=" in ln and ("play" in low or "pause" in low or "chord" in low):
            continue
        lines.append(ln)
    return "\n".join(lines)

# read a pasted sheet from stdin until the first blank line after it
def read_pasted():
    print("Paste sheet here\n")
    lines = []
    while True:
        try:
            ln = input()
        except EOFError:
            break
        if ln.strip():
            lines.append(ln)
        elif lines:
            break
    return "\n".join(lines)

# piano player entry point
def main():
    ap = argparse.ArgumentParser(description="Play a virtual-piano sheet")
    ap.add_argument("sheet", nargs="?",
                    help="optional path to a sheet file; omit to paste one in")
    ap.add_argument("--step", type=float, default=0.25,
                    help="seconds per note (default 0.25)")
    ap.add_argument("--rest", type=float, default=0.5,
                    help="seconds per - pause (default 0.5)")
    ap.add_argument("--floor", type=float, default=0.25,
                    help="fastest allowed gap between notes (default 0.25)")
    ap.add_argument("--near", type=float, default=0.25,
                    help="seconds between notes that sit close together "
                         "(default 0.25)")
    ap.add_argument("--near-dist", type=int, default=2, dest="near_dist",
                    help="how many keys apart still counts as close (default 2)")
    ap.add_argument("--jitter", type=float, default=0.12,
                    help="random timing wobble, 0 = perfectly even "
                         "(default 0.12 = up to 12%% longer)")
    ap.add_argument("--hold", type=float, default=0.03,
                    help="how long each key is held, seconds (default 0.03)")
    args = ap.parse_args()

    if args.sheet and Path(args.sheet).exists():
        text = Path(args.sheet).read_text(encoding="utf-8", errors="replace")
    else:
        text = read_pasted()

    if not text.strip():
        print("Nothing pasted.")
        return

    events = parse(clean(text))
    if not events:
        print("Nothing playable found in that sheet.")
        return

    notes = sum(1 for k, _ in events if k != "rest")
    nrest = sum(p for k, p in events if k == "rest")
    nsingle = sum(1 for k, p in events if k == "chord" and len(p) == 1)
    nchord = sum(1 for k, p in events if k == "chord" and len(p) > 1)
    print(f"\nParsed {notes} notes ({nchord} chords).")

    step = args.step
    rest = args.rest
    while True:
        try:
            typed = input(f"Seconds after a single note [{step}]: ").strip()
            if typed:
                step = float(typed)
            typed = input(f"Seconds after a chord / pause [{rest}]: ").strip()
            if typed:
                rest = float(typed)
        except (EOFError, ValueError):
            pass
        total = (nsingle * step + nchord * rest + nrest * rest) / 60.0
        print(f"  -> {step*1000:.0f}ms after a single note, "
              f"{rest*1000:.0f}ms after a chord/pause"
              f"  ->  about {total:.1f} minutes total")
        try:
            if input("  OK? [Y/n]: ").strip().lower() in ("", "y", "yes"):
                break
        except EOFError:
            break

    play(events, step=step, rest=rest, hold=args.hold,
         near=args.near, near_dist=args.near_dist, jitter=args.jitter,
         floor=args.floor)

if __name__ == "__main__":
    main()
