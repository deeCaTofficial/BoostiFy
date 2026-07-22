# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path


root = Path(SPECPATH)
runtime = Path(
    os.environ.get(
        "BOOSTIFY_RUNTIME_DIR",
        root / "BoostiFy" / "runtime" / "Worker" / "bin" / "x86" / "Release" / "net48",
    )
)
runtime_files = [
    "Boostify.Worker.exe",
    "Boostify.Worker.exe.config",
    "Boostify.Booster.exe",
    "Boostify.Booster.exe.config",
    "Boostify.Runtime.Steam.dll",
]
datas = [
    (str(root / "LICENSE"), "."),
    (str(root / "BoostiFy" / "Assets" / "BoostiFy.png"), "BoostiFy/Assets"),
    (str(root / "BoostiFy" / "Assets" / "BoostiFyLogo.png"), "BoostiFy/Assets"),
]
datas.extend((str(runtime / name), "BoostiFy/runtime/Worker/bin/x86/Release/net48") for name in runtime_files)

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BoostiFy",
    icon=str(root / "BoostiFy" / "runtime" / "Worker" / "boostify.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    version=str(root / "BoostiFy.version_info.txt"),
    console=False,
)
