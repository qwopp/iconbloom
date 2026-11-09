import pytest

from platform_win.ini import IniFile

STEAM = (
    b"[{000214A0-0000-0000-C000-000000000046}]\r\nProp3=19,0\r\n"
    b"[InternetShortcut]\r\nIDList=\r\nIconIndex=0\r\nURL=steam://rungameid/730\r\n"
    b"IconFile=C:\\Steam\\games\\cs.ico\r\n"
)


def test_reads_values_case_insensitively() -> None:
    ini = IniFile.parse(STEAM)
    assert ini.get("internetshortcut", "url") == "steam://rungameid/730"
    assert ini.get("InternetShortcut", "Missing") is None
    assert ini.get("Nope", "URL") is None


def test_untouched_file_round_trips_exactly() -> None:
    assert IniFile.parse(STEAM).to_bytes() == STEAM


def test_set_replaces_in_place_and_keeps_everything_else() -> None:
    ini = IniFile.parse(STEAM)
    ini.set("InternetShortcut", "IconFile", r"C:\Iconbloom\pink.ico")
    text = ini.to_bytes().decode("ascii")
    assert "IconFile=C:\\Iconbloom\\pink.ico\r\n" in text
    assert "Prop3=19,0" in text
    assert text.count("IconFile") == 1


def test_set_adds_keys_and_sections() -> None:
    ini = IniFile.parse(b"[A]\nx=1\n\n[B]\ny=2\n")
    ini.set("A", "z", "3")
    ini.set("C", "w", "4")
    assert ini.lines == ["[A]", "x=1", "z=3", "", "[B]", "y=2", "", "[C]", "w=4"]
    assert ini.newline == "\n"


def test_remove() -> None:
    ini = IniFile.parse(STEAM)
    ini.remove("InternetShortcut", "IconFile")
    ini.remove("InternetShortcut", "NotThere")
    assert ini.get("InternetShortcut", "IconFile") is None
    assert ini.has_entries()


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig"])
def test_bom_files_keep_their_encoding(encoding: str) -> None:
    data = "[.ShellClassInfo]\r\nInfoTip=Mes jeux\r\n".encode(encoding)
    ini = IniFile.parse(data)
    assert ini.get(".ShellClassInfo", "InfoTip") == "Mes jeux"
    assert ini.to_bytes() == data


def test_ansi_bytes_survive_a_round_trip() -> None:
    data = b"[A]\r\nname=Caf\xe9\r\n"
    ini = IniFile.parse(data)
    ini.set("A", "IconFile", "x.ico")
    assert ini.to_bytes().startswith(b"[A]\r\nname=Caf\xe9\r\n")


def test_paths_the_encoding_cannot_hold_switch_to_utf16() -> None:
    ini = IniFile.parse(b"[A]\r\nx=1\r\n")
    ini.set("A", "IconFile", "C:\\Users\\\u5c71\u7530\\pink.ico")
    data = ini.to_bytes()
    assert data.startswith("\ufeff".encode("utf-16-le"))
    assert IniFile.parse(data).get("A", "IconFile") == "C:\\Users\\\u5c71\u7530\\pink.ico"


def test_empty_file() -> None:
    ini = IniFile.parse(b"")
    assert not ini.has_entries()
    ini.set("S", "k", "v")
    assert ini.to_bytes() == b"[S]\r\nk=v\r\n"
