"""Command-line access to the same scan, apply and revert logic as the app.

    uv run python -m app.cli scan --dump-dir originals/

Every command that changes shortcuts accepts --dry-run.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from platform_win.extract import ExtractionError, extract_icon
from platform_win.shortcuts import ShellLinkIO, ShortcutGroup, default_roots, scan


def _cmd_scan(args: argparse.Namespace) -> int:
    groups = scan(default_roots(), ShellLinkIO())
    dump_dir: Path | None = args.dump_dir
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
    for group in groups:
        _print_group(group)
        if dump_dir is not None:
            _dump_original(group, dump_dir)
    print(f"\n{len(groups)} shortcut groups")
    return 0


def _print_group(group: ShortcutGroup) -> None:
    primary = group.primary
    lock = "" if group.writable else "  [read-only]"
    print(f"{group.name}{lock}")
    print(f"    target: {primary.info.target or '(none: Store or advertised app)'}")
    icon = primary.info.icon
    print(f"    icon:   {icon.path},{icon.index}" if icon.path else "    icon:   (target's icon)")
    for shortcut in group.shortcuts:
        print(f"    - {shortcut.source}: {shortcut.path}")


def _dump_original(group: ShortcutGroup, dump_dir: Path) -> None:
    primary = group.primary
    try:
        extracted = extract_icon(primary.info.icon, primary.info.target, primary.path)
    except ExtractionError as exc:
        print(f"    ! no icon: {exc}")
        return
    out = dump_dir / f"{group.slug}_{_safe(group.name)}.png"
    extracted.image.save(out)
    soft = " (small source, may look soft)" if extracted.upscaled else ""
    print(f"    saved {out.name} {extracted.image.size[0]}px from {extracted.source}{soft}")


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()[:40]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iconbloom-cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    scan_cmd = commands.add_parser("scan", help="list shortcuts and where their icons come from")
    scan_cmd.add_argument(
        "--dump-dir", type=Path, help="also save each original icon as a PNG in this folder"
    )
    scan_cmd.set_defaults(func=_cmd_scan)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
