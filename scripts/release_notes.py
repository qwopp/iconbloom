"""The CHANGELOG.md section for one version, for the GitHub release body.

uv run python -m scripts.release_notes 0.1.0                    # print it
uv run python -m scripts.release_notes 0.1.0 --output notes.md  # write it as UTF-8

The release workflow writes a file: a Windows console can't print every
character a changelog uses (such as the arrow in "More → Dark mode").
"""

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(version: str, text: str) -> str:
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    match = heading.search(text)
    if match is None:
        raise LookupError(f"CHANGELOG.md has no section for {version}")
    rest = text[match.end() :]
    following = re.search(r"^## \[|^\[[^\]]+\]: ", rest, re.MULTILINE)
    return rest[: following.start() if following else len(rest)].strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="release_notes")
    parser.add_argument("version")
    parser.add_argument("--output", type=Path, help="write UTF-8 to this file instead")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        notes = section(args.version.lstrip("v"), CHANGELOG.read_text(encoding="utf-8"))
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.output is None:
        print(notes)
    else:
        args.output.write_text(notes + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
