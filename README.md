# Rhythm Bot

Plays falling-note rhythm games, in 2-lane (guitar) or 4-lane (bass, drums, keys) mode. It watches each lane's arrow colour on screen, works out when each note will land, and holds the key for exactly as long as a hold bar measures. It only reads the screen: no game memory is read and nothing is injected.

Also includes a small player for pasted virtual-piano sheets.

## Requirements

- Windows
- A normal Python 3.13 build. `pywin32` crashes on free-threaded (no-GIL) builds, and `gilcheck.py` stops with a clear message if you're on one.

```
py -3.13 -m pip install pywin32 keyboard pillow
```

## Usage

```
py -3.13 menu.py
```

The menu shows the active mode and timing, and walks you through setup:

| Key | Action |
|---|---|
| `1` | Switch between 2 and 4 lanes |
| `2` | Calibrate: point at each receptor arrow |
| `4` | Preview: save `preview.png` to check the boxes line up |
| `5` | Debug: watch detection without sending keys |
| `6` | Run |
| `+` / `-` | Press 10 ms later or earlier |
| `t` | Test that key presses reach Windows |
| `l` | Run the offline logic tests |
| `b` | Benchmark capture and detection |
| `p` | Paste a piano sheet and auto-play it |

While running, `F7` pauses and `F8` quits, and both release any held keys.

2-lane and 4-lane are separate profiles in `config.json`. Positions are stored relative to the game window, so it can move freely, but recalibrate if its size changes.

## How it works

Each frame captures one tall strip per lane and matches pixels against that lane's arrow colour on all three channels. Seeing the whole lane is what handles the hard cases:

- **Notes are scheduled, not caught.** A note is spotted while it's still far up the lane, and its arrival time comes from its position and the fall speed. A dropped frame means one less position update, not a missed note.
- **Hold bars are measured.** A bar's length in pixels, divided by the fall speed, gives how long to hold.
- **Touching arrows are separated.** The seam between stacked arrows shows up as a dip in how much of the lane is covered, followed by a recovery. A hold bar's narrower tail only steps down, so it isn't split by mistake.
- **Fall speed is tracked live.** There's no BPM to set. Every tracked note feeds one shared estimate, which starts from the median of the first 7 samples and then follows tempo changes mid-song.
- **Late presses are dropped.** A press too far past its time is skipped rather than sent late, because it could only land on the wrong note.

### Speed

Capturing from the game's window own device context skips the desktop compositor:

| Method | Per grab | Rate |
|---|---|---|
| Desktop DC | 11.5 ms | ~85/sec |

Key presses go out through `SendInput` with hardware scan codes on their own thread, so a slow call can't stall capture.

## Tuning

Run the logic tests (`l`) after changing any timing value. They need no game, and cover overlapping notes, dropped frames, hold lengths, colour isolation and tempo changes.

| Setting | What it does |
|---|---|
| `press_lead` | When a press fires: raise it if early, lower it if late |
| `hue_tol` | How far a pixel can be from the lane's colour |
| `bar_min_px` | Shortest run that counts as a hold rather than a tap |
| `seam_drop` | How deep a dip must be to split touching notes |
| `min_press` | Shortest possible key press |

If two touching notes merge into one press, lower `seam_drop`. If a hold breaks into repeated taps, raise it.

## Files

| File | Purpose |
|---|---|
| `menu.py` | Menu, start here |
| `rhythm_bot.py` | Command line entry point, calibration and main loop |
| `detect.py` | Colour matching and per-lane note detection |
| `lane.py` | Note tracking and press timing |
| `keysender.py` | Key output on its own thread |
| `grabber.py` | Screen capture on its own thread |
| `capture.py` | Window capture |
| `speedtrack.py` | Live fall speed estimate |
| `config.py`, `config.json` | Profiles, defaults and calibration |
| `ui.py` | Console colours |
| `gilcheck.py` | Refuses to run on an incompatible Python build |
| `test_logic.py` | Offline tests |
| `piano.py` | Virtual-piano sheet player |
| `barlog.py`, `replay.py` | Log a run to a file, and replay it through the lane logic |
