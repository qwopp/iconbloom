# PyInstaller build for Iconbloom: one-folder, windowed.
#
#     uv run --group release pyinstaller installer/iconbloom.spec --noconfirm
#
# One-folder (not one-file) starts faster and trips fewer antivirus heuristics.
# SPECPATH, Analysis, PYZ, EXE and COLLECT are provided by PyInstaller.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))

from scripts.bundle import theme_files

datas = [
    (str(ROOT / "app" / "ui" / "style.qss"), "app/ui"),
    (str(ROOT / "app" / "ui" / "iconbloom.png"), "app/ui"),
    (str(ROOT / "app" / "ui" / "fonts"), "app/ui/fonts"),
]
datas += [(str(source), dest) for source, dest in theme_files(ROOT)]

# Only QtCore, QtGui and QtWidgets are used; keep the rest of Qt out of the build.
QT_EXCLUDES = [
    f"PySide6.{name}"
    for name in (
        "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
        "QtBluetooth", "QtCharts", "QtConcurrent", "QtDataVisualization", "QtDBus",
        "QtDesigner", "QtHelp", "QtLocation", "QtMultimedia", "QtMultimediaWidgets",
        "QtNetwork", "QtNfc", "QtOpenGL", "QtOpenGLWidgets", "QtPdf", "QtPdfWidgets",
        "QtPositioning", "QtPrintSupport", "QtQml", "QtQuick", "QtQuick3D",
        "QtQuickControls2", "QtQuickWidgets", "QtRemoteObjects", "QtScxml", "QtSensors",
        "QtSerialPort", "QtSql", "QtStateMachine", "QtSvg", "QtSvgWidgets", "QtTest",
        "QtTextToSpeech", "QtUiTools", "QtWebChannel", "QtWebEngineCore",
        "QtWebEngineWidgets", "QtWebSockets", "QtXml",
    )
]

OTHER_EXCLUDES = [
    "tkinter", "unittest", "pydoc", "hypothesis", "pytest",
    # Pillow's AVIF codec alone is ~8 MB, and icons are never AVIF.
    "PIL._avif", "PIL.AvifImagePlugin",
    # pywin32's MFC-based UI layer; only win32com.shell is used.
    "win32ui", "win32uiole", "dde", "pythonwin",
]

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    # IShellLink.GetPath returns file times, which pywin32 converts by importing
    # win32timezone at call time, out of sight of PyInstaller's analysis.
    hiddenimports=["win32com.shell.shell", "win32com.shell.shellcon", "win32timezone"],
    excludes=[*QT_EXCLUDES, *OTHER_EXCLUDES],
    noarchive=False,
)

# Files the hooks bring along that Iconbloom never loads.
DROP_FILES = {"opengl32sw.dll", "qt6network.dll", "qt6pdf.dll", "qt6svg.dll", "mfc140u.dll"}
KEEP_PLUGINS = ("plugins/platforms/qwindows.dll", "plugins/styles/")


def wanted(entry):
    dest = entry[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1].lower()
    if name in DROP_FILES or "PySide6/translations/" in dest:
        return False
    if "PySide6/plugins/" in dest:
        return any(keep in dest for keep in KEEP_PLUGINS)
    return True


a.binaries = [b for b in a.binaries if wanted(b)]
a.datas = [d for d in a.datas if wanted(d)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Iconbloom",
    icon=str(ROOT / "installer" / "iconbloom.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Iconbloom",
    upx=False,
)
