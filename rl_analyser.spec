# PyInstaller build for RL Analyser: a windowed one-folder app (dist/RL Analyser/).
# Build with build.ps1 (or: pyinstaller rl_analyser.spec --noconfirm).
# One folder rather than one file: the bundled AI engine is ~150 MB, and a single exe would
# unpack all of it on every launch.

import os

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("webview.platforms") + ["clr_loader", "pythonnet"]

a = Analysis(
    ["rl_analyser.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("ui", "ui"),
        ("tools", "tools"),       # rrrocket.exe, llama-server/ (+ licences)
    ] + ([("benchmarks.json", ".")] if os.path.exists("benchmarks.json") else []),   # rank tables (dev_tools/build_benchmarks.py)
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "IPython", "pytest", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RL Analyser",
    console=False,            # no console window
    icon="assets/icon.ico",
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="RL Analyser",
    upx=False,
)
