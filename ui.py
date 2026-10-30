import os
import sys

# make stdout speak utf-8 on windows
def _force_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

_force_utf8()

RULE_CHAR = "─"

# turn on ansi color codes in the console
def _enable_ansi():
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        k32.SetConsoleMode(h, mode.value | 0x0004)  # VIRTUAL_TERMINAL_PROCESSING
        return True
    except Exception:
        return False

COLOUR = _enable_ansi() and sys.stdout.isatty()

# an ansi code, or nothing when colors are off
def _c(code):
    return code if COLOUR else ""

RESET = _c("\033[0m")
BOLD = _c("\033[1m")
DIM = _c("\033[2m")

RED = _c("\033[38;5;203m")
GREEN = _c("\033[38;5;114m")
YELLOW = _c("\033[38;5;221m")
BLUE = _c("\033[38;5;75m")

# The five arrow colours.
LANE_COLOURS = {
    "cyan":    _c("\033[38;5;80m"),
    "magenta": _c("\033[38;5;177m"),
    "violet":  _c("\033[38;5;141m"),
    "pink":    _c("\033[38;5;211m"),
    "orange":  _c("\033[38;5;215m"),
}

# ansi color for a lane hue
def lane_colour(hue):
    return LANE_COLOURS.get(hue, BLUE)

# wrap text bold
def bold(s):
    return f"{BOLD}{s}{RESET}"

# wrap text dim grey
def dim(s):
    return f"{DIM}{s}{RESET}"

# wrap text red
def red(s):
    return f"{RED}{s}{RESET}"

# wrap text green
def ok(s):
    return f"{GREEN}{s}{RESET}"

# wrap text orange
def warn(s):
    return f"{YELLOW}{s}{RESET}"

# style a key name
def key(s):
    return f"{BOLD}{YELLOW}{s}{RESET}"

# colored label like L->T(cyan)
def lane_tag(name, keyname, hue=None):
    c = lane_colour(hue)
    return f"{c}{name}{RESET}{DIM}->{RESET}{c}{BOLD}{keyname.upper()}{RESET}"

# print a titled divider
def header(title):
    line = RULE_CHAR * 52
    print(f"\n{BLUE}{line}{RESET}")
    print(f"  {BOLD}{title}{RESET}")
    print(f"{BLUE}{line}{RESET}")

# print a label and value line
def field(label, value, colour=None):
    c = colour or ""
    end = RESET if colour else ""
    print(f"  {DIM}{label:<18}{RESET} {c}{value}{end}")
