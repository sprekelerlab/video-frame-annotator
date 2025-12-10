#!/usr/bin/env python3
"""
Test script to verify that Python can load libmpv.

Run this after installing MPV to ensure python-mpv can find and load libmpv.
"""

import sys

from mpv_utils import _format_mpv_import_error


try:
    import mpv

    # Try to create an MPV instance
    player = mpv.MPV()
    print("✓ libmpv loaded successfully!")
    player.terminate()
    sys.exit(0)
except Exception as exc:
    error_msg = _format_mpv_import_error(exc)
    print(f"✗ {error_msg}", file=sys.stderr)
    sys.exit(1)
