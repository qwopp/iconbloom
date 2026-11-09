"""Print the CHANGELOG.md section for one version, for the GitHub release body.

uv run python -m scripts.release_notes 0.1.0
"""

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
    if len(argv) != 1:
        print("usage: python -m scripts.release_notes VERSION", file=sys.stderr)
        return 2
    try:
        print(section(argv[0].lstrip("v"), CHANGELOG.read_text(encoding="utf-8")))
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
