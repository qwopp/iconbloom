# Iconbloom

Restyle your Windows desktop into one cute, matching theme, one icon at a time. Offline, instant, and undoable with one click.

[![CI](https://github.com/qwopp/iconbloom/actions/workflows/ci.yml/badge.svg)](https://github.com/qwopp/iconbloom/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-ff9ec4.svg)](LICENSE)

[![Download for Windows](https://img.shields.io/badge/Download_for_Windows-Iconbloom-2ea44f?style=for-the-badge)](https://github.com/qwopp/iconbloom/releases/latest)

![Sample icons before and after the Kawaii Pink theme](docs/screenshots/before-after.png)

![Picking a style for each icon](docs/screenshots/picker.gif)

## How it works

Pick an icon, choose one of 20 styled versions of its real icon, and click **Apply**. Nothing is AI-generated: every style is the app's own icon run through filters, frames and hand-drawn decorations.

- **Works on** shortcuts (including Steam and Epic games), desktop folders, taskbar pins, the Start menu, and the Recycle Bin, This PC, Network and your user folder.
- An app with shortcuts in several places is one tile, styled everywhere at once.
- Ctrl/Shift-click to style several icons together. **Use my own image…** takes any PNG.
- **Revert** or **Revert all** puts originals back. The uninstaller offers to as well.

## What it changes

Only which icon something shows: never what it opens, and never your apps.

| Item | Where the icon setting lives |
|---|---|
| Shortcuts | The icon field in the `.lnk` or `.url` file |
| Folders | A hidden `desktop.ini` in the folder, as Windows' own *Change Icon* writes it (syncs with OneDrive) |
| Recycle Bin, This PC, Network, user folder | Your user's registry setting, as Windows' *Desktop icon settings* writes it |
| Start menu apps installed for all users | Same as shortcuts. Windows asks for permission first |

It can't change running apps that aren't pinned, Store apps in Start, Alt+Tab or title bars. Those icons come from the apps themselves.

Before changing anything, Iconbloom saves an exact copy of it in `%LOCALAPPDATA%\Iconbloom`. Revert restores that copy.

## FAQ

**"Windows protected your PC"?** Releases aren't code-signed yet. Click **More info → Run anyway**. Each release lists SHA-256 checksums to verify your download.

**An icon still looks old?** Windows caches icons, the taskbar especially. Use **More → Refresh Windows icons**.

**An app update reset an icon?** Use **More → Reapply my icons**.

**Internet use?** Only an update check when it opens (untick **Check for updates** to stop it). Updates install only when you click **Update now**, and only after the download matches its published checksum.

## Build from source

Needs Windows 10 or 11 and [uv](https://docs.astral.sh/uv/).

```powershell
git clone https://github.com/qwopp/iconbloom
cd iconbloom
uv sync
uv run python -m app.main
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers tests, themes and releases. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how it fits together.

## License

[MIT](LICENSE). Nunito font under the [SIL Open Font License](app/ui/fonts/OFL.txt). All artwork drawn for this project.
