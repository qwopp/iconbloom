"""Command-line access to the same scan, apply and revert logic as the app.

    uv run python -m app.cli scan --dump-dir originals/
    uv run python -m app.cli apply "Firefox" --recipe tile_bow --dry-run
    uv run python -m app.cli revert-all

Every command that changes shortcuts accepts --dry-run.
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from app.choices import Choice
from app.service import ChangeReport, IconService, windows_service
from engine.themes import DEFAULT_THEME, ThemeError
from platform_win.backup import BackupCorruptError
from platform_win.extract import ExtractionError
from platform_win.shortcuts import ShortcutGroup

type Command = Callable[[argparse.Namespace, IconService], int]

SHARED_HELP = "also change shortcuts every user shares (Windows asks for permission)"


def _cmd_scan(args: argparse.Namespace, service: IconService) -> int:
    groups = service.scan()
    dump_dir: Path | None = args.dump_dir
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
    for group in groups:
        _print_group(service, group)
        if dump_dir is not None:
            _dump_original(service, group, dump_dir)
    print(f"\n{len(groups)} shortcut groups")
    return 0


def _cmd_apply(args: argparse.Namespace, service: IconService) -> int:
    target = _find(service, args.name)
    service.theme(args.theme).recipe(args.recipe)  # fail early on a typo
    choice = Choice(args.theme, args.recipe, seed=args.seed)
    return _report(
        service.apply(target, choice, include_shared=args.include_shared, dry_run=args.dry_run)
    )


def _cmd_revert(args: argparse.Namespace, service: IconService) -> int:
    return _report(service.revert(_find(service, args.name), dry_run=args.dry_run))


def _cmd_revert_all(args: argparse.Namespace, service: IconService) -> int:
    return _report(service.revert_all(dry_run=args.dry_run))


def _cmd_cleanup(args: argparse.Namespace, service: IconService) -> int:
    return _report(service.cleanup(dry_run=args.dry_run))


def _cmd_reapply(args: argparse.Namespace, service: IconService) -> int:
    groups = service.scan()
    return _report(
        service.reapply(groups, include_shared=args.include_shared, dry_run=args.dry_run)
    )


def _find(service: IconService, name: str) -> ShortcutGroup:
    matches = [g for g in service.scan() if g.name.casefold() == name.casefold()]
    if not matches:
        raise LookupError(f"no shortcut named {name!r}; run 'scan' to list them")
    return matches[0]


def _report(report: ChangeReport) -> int:
    verb = "would" if report.dry_run else "did"
    for path in report.written:
        print(f"{verb} write  {path}")
    for path in report.changed:
        print(f"{verb} change {path}")
    for path in report.removed:
        print(f"{verb} delete {path}")
    for path, reason in report.skipped:
        print(f"skipped     {path}: {reason}")
    if not (report.written or report.changed or report.removed or report.skipped):
        print("nothing to do")
    return 0


def _print_group(service: IconService, group: ShortcutGroup) -> None:
    primary = group.primary
    lock = "" if group.own_shortcuts else "  [shared: needs administrator permission]"
    print(f"{group.name}  ({service.status(group)}){lock}")
    print(f"    target: {primary.info.target or '(none: Store or advertised app)'}")
    icon = primary.info.icon
    print(f"    icon:   {icon.path},{icon.index}" if icon.path else "    icon:   (target's icon)")
    for shortcut in group.shortcuts:
        print(f"    - {shortcut.source}: {shortcut.path}")


def _dump_original(service: IconService, group: ShortcutGroup, dump_dir: Path) -> None:
    try:
        extracted = service.original_icon(group)
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
    parser = argparse.ArgumentParser(prog="iconbloom-cli", description="Theme shortcut icons.")
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func: Command, help_text: str, *, changes: bool) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(func=func)
        if changes:
            sub.add_argument(
                "--dry-run", action="store_true", help="show what would change, change nothing"
            )
        return sub

    scan_cmd = add("scan", _cmd_scan, "list shortcuts and their icon sources", changes=False)
    scan_cmd.add_argument("--dump-dir", type=Path, help="save each original icon as a PNG here")

    apply_cmd = add("apply", _cmd_apply, "theme one shortcut", changes=True)
    apply_cmd.add_argument("name", help="shortcut name as shown by 'scan'")
    apply_cmd.add_argument("--recipe", required=True, help="recipe id from the theme")
    apply_cmd.add_argument("--theme", default=DEFAULT_THEME)
    apply_cmd.add_argument("--seed", type=int, default=0, help="0 = default look, others shuffle")
    apply_cmd.add_argument("--include-shared", action="store_true", help=SHARED_HELP)

    revert_cmd = add("revert", _cmd_revert, "restore one shortcut's original icon", changes=True)
    revert_cmd.add_argument("name")
    add("revert-all", _cmd_revert_all, "restore every changed shortcut", changes=True)
    add("cleanup", _cmd_cleanup, "delete generated icons nothing uses", changes=True)
    reapply_cmd = add(
        "reapply", _cmd_reapply, "re-theme shortcuts that lost their icon", changes=True
    )
    reapply_cmd.add_argument("--include-shared", action="store_true", help=SHARED_HELP)
    return parser


def main(
    argv: Sequence[str] | None = None,
    make_service: Callable[[], IconService] = windows_service,
) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        service = make_service()
        return args.func(args, service)
    except BackupCorruptError as exc:
        print(f"Refusing to change anything: {exc}", file=sys.stderr)
        return 2
    except (LookupError, ThemeError, ExtractionError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
