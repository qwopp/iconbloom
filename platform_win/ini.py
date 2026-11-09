"""Edit Windows INI files (.url shortcuts, desktop.ini) without disturbing the rest.

Windows reads these files through its old "profile" APIs, which accept ANSI
or UTF-16 with a byte-order mark. Edits keep every other line, the file's
line endings and, when possible, its encoding.
"""

from dataclasses import dataclass

_BOMS = ((b"\xff\xfe", "utf-16"), (b"\xef\xbb\xbf", "utf-8-sig"))


@dataclass
class IniFile:
    lines: list[str]
    encoding: str = "ascii"
    newline: str = "\r\n"

    @classmethod
    def parse(cls, data: bytes) -> "IniFile":
        encoding = next((name for bom, name in _BOMS if data.startswith(bom)), None)
        if encoding is None:
            # Without a BOM, Windows reads the file in the ANSI code page. Plain
            # ASCII stays ASCII; anything else round-trips byte for byte, and new
            # text it can't hold switches the file to UTF-16 (see to_bytes).
            encoding = "ascii" if data.isascii() else "latin-1"
        text = data.decode(encoding)
        newline = "\r\n" if "\r\n" in text or not text else "\n"
        return cls(text.splitlines(), encoding, newline)

    def get(self, section: str, key: str) -> str | None:
        found = self._find(section, key)
        if found is None:
            return None
        return self.lines[found].split("=", 1)[1].strip()

    def set(self, section: str, key: str, value: str) -> None:
        line = f"{key}={value}"
        found = self._find(section, key)
        if found is not None:
            self.lines[found] = line
            return
        start = self._section_start(section)
        if start is None:
            if self.lines and self.lines[-1].strip():
                self.lines.append("")
            self.lines += [f"[{section}]", line]
            return
        end = self._section_end(start)
        # Insert after the section's last entry, before any blank lines that follow it.
        while end > start + 1 and not self.lines[end - 1].strip():
            end -= 1
        self.lines.insert(end, line)

    def remove(self, section: str, key: str) -> None:
        found = self._find(section, key)
        if found is not None:
            del self.lines[found]

    def has_entries(self) -> bool:
        return any("=" in line for line in self.lines)

    def to_bytes(self) -> bytes:
        text = self.newline.join(self.lines) + self.newline
        try:
            return text.encode(self.encoding)
        except UnicodeEncodeError:
            # A path the file's encoding can't hold: Windows also reads UTF-16 with a BOM.
            return text.encode("utf-16")

    def _section_start(self, section: str) -> int | None:
        wanted = f"[{section}]".casefold()
        for i, line in enumerate(self.lines):
            if line.strip().casefold() == wanted:
                return i
        return None

    def _section_end(self, start: int) -> int:
        for i in range(start + 1, len(self.lines)):
            if self.lines[i].strip().startswith("["):
                return i
        return len(self.lines)

    def _find(self, section: str, key: str) -> int | None:
        start = self._section_start(section)
        if start is None:
            return None
        for i in range(start + 1, self._section_end(start)):
            name, sep, _ = self.lines[i].partition("=")
            if sep and name.strip().casefold() == key.casefold():
                return i
        return None
