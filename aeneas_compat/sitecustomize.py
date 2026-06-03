"""Compatibility patches loaded before aeneas subprocesses start."""

import time


_original_sleep = time.sleep


def _sleep(seconds):
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        pass
    return _original_sleep(seconds)


time.sleep = _sleep
