"""Where the app's files live, whether run from source or from a packaged (PyInstaller) build.

`bundled(...)` is for files shipped with the app (tools/, ui/). `user_data(...)` is for
files the app creates (config.json, cache/). From source both are the project folder, so
nothing moves for developers; in a packaged build user data goes to %LOCALAPPDATA%\\RLAnalyser
because the install folder may be read-only. `models_dir()` is always under LOCALAPPDATA,
since AI model files are multi-GB and must survive app updates.
"""

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "RLAnalyser"


def bundled(*parts):
    return APP_DIR.joinpath(*parts)


def user_data(*parts):
    if FROZEN:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)   # first run after install: the folder doesn't exist yet
    return (LOCAL_DIR if FROZEN else Path(__file__).parent).joinpath(*parts)


def models_dir():
    return LOCAL_DIR / "models"
