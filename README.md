# Iconbloom

Restyle your Windows desktop into one cute, matching theme, one icon at a time. Offline, instant, and undoable with one click.

[![CI](https://github.com/qwopp/iconbloom/actions/workflows/ci.yml/badge.svg)](https://github.com/qwopp/iconbloom/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ff9ec4.svg)](LICENSE)

[![Download for Windows](https://img.shields.io/badge/Download_for_Windows-Iconbloom-2ea44f?style=for-the-badge)](https://github.com/qwopp/iconbloom/releases/latest)

![Sample icons before, and in every theme](docs/screenshots/before-after.png)

![Picking styles, switching themes and dark mode](docs/screenshots/picker.gif)

## FAQ

**Can I undo it?** Yes. **Revert** or **Revert all** puts every original back, and so does the uninstaller. Iconbloom only changes which icon something shows, never your apps.

**Can it style the taskbar too?** Yes. Open **Taskbar** at the top to give it your theme's color, frosted glass and layout, with a live preview. It uses Windows' own settings, and **Revert** puts them back.

**"Windows protected your PC"?** Releases aren't code-signed yet. Click **More info → Run anyway**. Each release lists SHA-256 checksums to verify your download.

**An icon still looks old?** Windows caches icons, the taskbar especially. Use **More → Refresh Windows icons**.

**An app update reset an icon?** Use **More → Reapply my icons**.

**Internet use?** Only an update check when it opens (untick **Check for updates** to stop it). Updates install only when you click **Update now**.

## Build from source

Needs Windows 10 or 11 and [uv](https://docs.astral.sh/uv/): `uv sync`, then `uv run python -m app.main`.

[CONTRIBUTING.md](CONTRIBUTING.md) covers tests, themes and releases. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how it fits together.

## License

[MIT](LICENSE). Nunito font under the [SIL Open Font License](app/ui/fonts/OFL.txt). All artwork drawn for this project.
