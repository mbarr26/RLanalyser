# PyInstaller build for RL Analyser: a windowed one-folder app (dist/RL Analyser/).
# Build with build.ps1 (or: pyinstaller rl_analyser.spec --noconfirm).
# One folder rather than one file: the bundled AI engine is ~150 MB, and a single exe would
# unpack all of it on every launch.

import os

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

hiddenimports = collect_submodules("webview.platforms") + ["clr_loader", "pythonnet"]
# keyring (the saved sign-in) finds its Windows Credential Manager backend through package metadata,
# which PyInstaller doesn't copy by default. Without these the installed app would silently forget the
# sign-in every time it closes.
hiddenimports += collect_submodules("keyring.backends") + ["win32ctypes.core", "win32ctypes.pywin32"]
metadata = copy_metadata("keyring") + copy_metadata("jaraco.classes") + copy_metadata("jaraco.functools") + copy_metadata("jaraco.context")

# A DEMO build (release.ps1 -Demo) bundles a flag file that makes the app run its pretend account service.
# Normal builds never contain it, so they can't ship pretend payments by accident.
demo_files = []
if os.environ.get("RLA_DEMO_BUILD"):
    with open("demo.flag", "w") as f:
        f.write("demo build: pretend accounts and payments")
    demo_files = [("demo.flag", ".")]

a = Analysis(
    ["rl_analyser.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("ui", "ui"),
        ("tools", "tools"),       # rrrocket.exe, llama-server/ (+ licences)
    ] + metadata + demo_files + ([("benchmarks.json", ".")] if os.path.exists("benchmarks.json") else []),   # rank tables (dev_tools/build_benchmarks.py)
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
