import sys

# pywin32 crashes with no python error under a free-threaded build, so refuse early
if getattr(sys, "_is_gil_enabled", lambda: True)() is False:
    sys.exit(
        f"\n  {sys.executable}\n  is a free-threaded (no-GIL) build of Python.\n\n"
        "  pywin32 is not compatible with it and crashes instantly\n"
        "  (STATUS_ACCESS_VIOLATION) as soon as win32gui is imported,\n"
        "  with no Python error - which looks like the program just did\n"
        "  nothing.\n\n"
        "  Run this with a normal Python build instead, e.g.:\n"
        "    py -3.13 menu.py\n\n"
    )
