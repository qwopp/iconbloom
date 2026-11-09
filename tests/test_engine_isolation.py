"""engine/ must stay OS-free so it runs on any platform and can back a Mac port."""

import ast
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"

FORBIDDEN_ROOTS = frozenset(
    {
        "app",
        "ctypes",
        "platform_win",
        "pythoncom",
        "pywintypes",
        "PySide6",
        "subprocess",
        "win32api",
        "win32com",
        "win32con",
        "win32gui",
        "win32ui",
        "winreg",
    }
)


def _imported_roots(source: str) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_engine_imports_no_os_specific_modules() -> None:
    offenders: dict[str, list[str]] = {}
    for path in ENGINE_DIR.rglob("*.py"):
        bad = _imported_roots(path.read_text(encoding="utf-8")) & FORBIDDEN_ROOTS
        if bad:
            offenders[str(path.relative_to(ENGINE_DIR))] = sorted(bad)
    assert not offenders, f"engine/ must stay OS-free, found: {offenders}"


def test_guard_detects_forbidden_import() -> None:
    assert _imported_roots("import win32api\nfrom PySide6 import QtCore") == {"win32api", "PySide6"}
