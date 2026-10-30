import os
import sys
import subprocess

import gilcheck  # noqa: F401  (must run before anything imports win32gui)
import config
import ui

PY = sys.executable

try:
    import win32gui  # noqa: F401
except ImportError:
    print(ui.red(f"\n  pywin32 is not installed for {PY}."))
    print(f"  Run: {ui.bold(f'\"{PY}\" -m pip install pywin32')}")
    sys.exit(1)

# run one of the bot scripts as a subprocess
def run(*args):
    here = os.path.dirname(os.path.abspath(__file__))
    cmd = [PY, "-u", *args]
    print(ui.dim(f"  $ {' '.join(cmd)}\n"))
    try:
        r = subprocess.run(cmd, cwd=here)
        if r.returncode != 0:
            print(ui.red(f"\n  [exited with code {r.returncode} — see output "
                         f"above for the error]"))
    except FileNotFoundError as e:
        print(ui.red(f"\n  Could not launch: {e}"))
    except KeyboardInterrupt:
        pass
    input(ui.dim("\n  [enter] back to menu "))

# print the current mode, calibration and timing
def status():
    doc = config.load_doc()
    active = doc.get("active", "2lane")

    os.system("cls" if os.name == "nt" else "clear")
    ui.header("ROBLOX RHYTHM BOT")

    for mode in ("2lane", "4lane"):
        prof = doc["profiles"][mode]
        lanes = prof.get("lanes", [])
        mark = ui.ok(" active ") if mode == active else "        "
        tags = "  ".join(ui.lane_tag(l["name"], l["key"], l.get("hue"))
                         for l in lanes)
        cal = "" if prof.get("_calibrated") else ui.dim("  (not calibrated)")
        label = "2 lanes  guitar" if mode == "2lane" else "4 lanes  bass/drums"
        print(f" {mark} {ui.bold(label):<28} {tags}{cal}")

    prof = doc["profiles"][active]
    print()
    ui.field("fall speed",
             f"{prof.get('fall_speed', 0):.5f} px/s   "
             f"{ui.dim('(live-tracked while playing)')}")
    ui.field("press lead", f"{prof.get('press_lead', 0)*1000:.5f} ms")
    ui.field("hit zone",
             f"y{prof.get('receptor_y', 0) - prof.get('hit_above', 0)}"
             f"..y{prof.get('receptor_y', 0)}")
    return active

MENU = [
    ("1", "Switch lane mode", "2 lanes <-> 4 lanes"),
    ("2", "Calibrate", "point at the arrows for this mode"),
    ("", "", ""),
    ("4", "Preview", "check the boxes line up (preview.png)"),
    ("5", "Debug", "watch detection, sends NO keys"),
    ("6", "RUN", "play — fall speed is tracked live, no BPM needed"),
    ("", "", ""),
    ("+", "Press later", "+10ms   if it hits EARLY"),
    ("-", "Press earlier", "-10ms   if it hits LATE"),
    ("", "", ""),
    ("t", "Test keys", "does key output reach Windows?"),
    ("l", "Test logic", "offline timing checks"),
    ("b", "Benchmark", "capture + detection speed"),
    ("p", "Piano", "paste a sheet and auto-play it"),
    ("x", "Exit", ""),
]

BOT_ACTIONS = {
    "2": ["--calibrate"],
    "4": ["--preview"],
    "5": ["--debug"],
    "6": [],
    "+": ["--nudge", "10"],
    "-": ["--nudge", "-10"],
    "t": ["--testkeys"],
    "b": ["--bench"],
}
SCRIPTS = {"l": "test_logic.py", "p": "piano.py"}

# the interactive menu loop
def main():
    while True:
        active = status()
        mode_flag = "2" if active == "2lane" else "4"
        print()
        for k, label, hint in MENU:
            if not k:
                print()
                continue
            print(f"   {ui.key(k)}  {label:<16} {ui.dim(hint)}")

        try:
            choice = input(f"\n  {ui.bold('>')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return

        if choice == "1":
            config.set_active("4lane" if active == "2lane" else "2lane")
        elif choice in BOT_ACTIONS:
            run("rhythm_bot.py", *BOT_ACTIONS[choice], "--mode", mode_flag)
        elif choice in SCRIPTS:
            run(SCRIPTS[choice])
        elif choice in ("x", "q"):
            return

if __name__ == "__main__":
    main()
