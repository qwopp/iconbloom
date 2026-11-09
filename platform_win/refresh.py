"""Ask Explorer to redraw icons after shortcuts change.

Windows caches icons hard. The gentle notification below is usually enough
for the desktop and Start menu; taskbar pins may need the hard refresh,
which restarts Explorer and must only run after the user agrees.
"""

import subprocess


def notify_icons_changed() -> None:
    from win32com.shell import shell, shellcon

    shell.SHChangeNotify(shellcon.SHCNE_ASSOCCHANGED, shellcon.SHCNF_IDLIST, None, None)


def hard_refresh() -> None:
    """Rebuild the icon cache and restart Explorer. Briefly hides the taskbar."""
    subprocess.run(["ie4uinit.exe", "-show"], check=False, timeout=60)
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], check=False, timeout=60)
    subprocess.Popen(["explorer.exe"])  # detached: Explorer keeps running after we exit
