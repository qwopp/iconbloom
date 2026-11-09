import pytest

from app import __version__
from scripts.release_notes import CHANGELOG, main, section

SAMPLE = """# Changelog

## [Unreleased]

## [1.1.0] - 2027-01-01

### Fixed

- A thing.

## [1.0.0] - 2026-12-01

- First.

[1.1.0]: https://example.com
"""


def test_section_stops_at_next_heading() -> None:
    assert section("1.1.0", SAMPLE) == "### Fixed\n\n- A thing."


def test_last_section_stops_at_link_references() -> None:
    assert section("1.0.0", SAMPLE) == "- First."


def test_missing_version() -> None:
    with pytest.raises(LookupError, match=r"no section for 2\.0\.0"):
        section("2.0.0", SAMPLE)


def test_changelog_has_notes_for_current_version() -> None:
    notes = section(__version__, CHANGELOG.read_text(encoding="utf-8"))
    # Keep a Changelog groups notes under "### Added", "### Changed", "### Fixed" and so on.
    assert notes.startswith("### ")
    assert "\n- " in notes


def test_cli(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([f"v{__version__}"]) == 0
    assert capsys.readouterr().out.strip() == section(
        __version__, CHANGELOG.read_text(encoding="utf-8")
    )
    assert main(["0.0.0"]) == 1
    assert main([]) == 2
