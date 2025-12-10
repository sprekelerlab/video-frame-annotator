#!/usr/bin/env python3
"""
Utility functions for MPV import error handling.
"""

import shutil
import sys
from pathlib import Path
from typing import Optional


class MPVImportError(RuntimeError):
    """Raised when MPV cannot be imported or its library is missing."""


def _format_mpv_import_error(exc: Exception) -> str:
    """
    Build a platform-aware help message for MPV import failures.

    Parameters
    ----------
    exc : Exception
        The original exception raised during MPV import.

    Returns
    -------
    str
        An error message including platform info, detected mpv binary path,
        and remediation tips.
    """
    platform_name = sys.platform.lower()
    mpv_path: Optional[str] = shutil.which("mpv")
    mpv_dir = Path(mpv_path).parent if mpv_path else None

    tips = []
    if platform_name.startswith("darwin"):
        homebrew_lib = str(Path(mpv_dir.parent, "lib")) if mpv_dir else "/opt/homebrew/lib"
        if mpv_path:
            tips.append(f"mpv found at: {mpv_path}")
            tips.append(
                "If import still fails, export the Homebrew lib dir so Python can load libmpv:"
                f" `export DYLD_FALLBACK_LIBRARY_PATH=\"{homebrew_lib}:$DYLD_FALLBACK_LIBRARY_PATH\"`"
            )
            tips.append(f"Ensure `libmpv.dylib` exists in {homebrew_lib}.")
        else:
            tips.append("mpv not found. Install via Homebrew: `brew install mpv`.")
            tips.append("After install, the library usually resides in /opt/homebrew/lib.")
    elif platform_name.startswith("linux"):
        lib_guess = str(Path(mpv_dir.parent, "lib")) if mpv_dir else "/usr/lib"
        if mpv_path:
            tips.append(f"mpv found at: {mpv_path}")
            tips.append(
                "If import still fails, point the loader to libmpv:"
                f" `export LD_LIBRARY_PATH=\"{lib_guess}:$LD_LIBRARY_PATH\"`"
            )
            tips.append(f"Ensure `libmpv.so` exists in {lib_guess} (package libmpv).")
        else:
            tips.append("mpv not found. Install mpv (e.g., `sudo apt install mpv libmpv1`).")
    elif platform_name.startswith("win"):
        if mpv_path:
            tips.append(f"mpv found at: {mpv_path}")
            tips.append(
                "If import still fails, add the mpv folder to PATH in this shell:"
                f" `set PATH=\"{mpv_dir}\";%PATH%`"
            )
            tips.append("Ensure mpv-*.dll (libmpv) lives in the same folder as mpv.exe.")
        else:
            tips.append("mpv not found. Install from https://mpv.io/installation/ and add its folder to PATH.")
    else:
        tips.append("mpv not found for this platform. Install mpv and ensure libmpv is on the loader path.")

    mpv_hint = mpv_path or "not found in PATH"
    tip_text = " ".join(tips)
    return (
        "Failed to import MPV (python-mpv). "
        f"Platform: {platform_name}. "
        f"mpv in PATH: {mpv_hint}. "
        f"Original error: {exc}. "
        f"Tips: {tip_text}"
    )
