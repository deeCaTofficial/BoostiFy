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
    # Значок окна — из .ico; BoostiFyLogo.png (2048 px, ~1 МБ) в сборке не нужен.
    (str(root / "BoostiFy" / "runtime" / "Worker" / "boostify.ico"), "BoostiFy/runtime/Worker"),
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
    # Архивы bz2/lzma/zstd программе не нужны: zipfile, tarfile и shutil
    # сами обходятся без них, если модулей нет.
    excludes=["bz2", "_bz2", "lzma", "_lzma", "compression.zstd", "_zstd"],
    noarchive=False,
)


# Хуки PyQt6 кладут в сборку всё подряд. Окну нужны только Core/Gui/Widgets,
# платформа Windows (offscreen — для проверок без окна), стиль и чтение .ico.
# Остальное не загружается никогда, но занимало ~13 МБ из ~40:
# opengl32sw.dll — программный OpenGL, а интерфейс рисуется без OpenGL;
# Qt6Pdf/Qt6Svg/Qt6Network нужны только плагинам pdf, svg и TUIO-тачскрина;
# переводы Qt программа не подключает (QTranslator нет), подписи — свои.
QT_UNUSED = (
    "pyqt6/qt6/bin/opengl32sw.dll",
    "pyqt6/qt6/bin/qt6pdf.dll",
    "pyqt6/qt6/bin/qt6svg.dll",
    "pyqt6/qt6/bin/qt6network.dll",
    "pyqt6/qt6/translations/",
    "pyqt6/qt6/plugins/iconengines/",
    "pyqt6/qt6/plugins/generic/",
    "pyqt6/qt6/plugins/platforms/qminimal.dll",
)
QT_IMAGE_FORMATS = "pyqt6/qt6/plugins/imageformats/"


def needed(entry):
    dest = entry[0].replace("\\", "/").lower()
    if dest.startswith(QT_IMAGE_FORMATS):
        return dest.endswith("/qico.dll")
    return not dest.startswith(QT_UNUSED)


a.binaries = [entry for entry in a.binaries if needed(entry)]
a.datas = [entry for entry in a.datas if needed(entry)]

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
