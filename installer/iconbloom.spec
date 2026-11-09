# PyInstaller build for Iconbloom: one-folder, windowed.
#
#     uv run --group release pyinstaller installer/iconbloom.spec --noconfirm
#
# One-folder (not one-file) starts faster and trips fewer antivirus heuristics.
# SPECPATH, Analysis, PYZ, EXE and COLLECT are provided by PyInstaller.

from pathlib import Path

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "app" / "ui" / "style.qss"), "app/ui"),
    (str(ROOT / "app" / "ui" / "iconbloom.png"), "app/ui"),
    (str(ROOT / "app" / "ui" / "fonts"), "app/ui/fonts"),
]
for theme in sorted((ROOT / "themes").iterdir()):
    if (theme / "theme.json").is_file():
        datas.append((str(theme / "theme.json"), f"themes/{theme.name}"))
        datas += [(str(png), f"themes/{theme.name}") for png in theme.glob("*.png")]

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

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=["win32com.shell.shell", "win32com.shell.shellcon"],
    excludes=[*QT_EXCLUDES, "tkinter", "unittest", "pydoc", "hypothesis", "pytest"],
    noarchive=False,
)
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
