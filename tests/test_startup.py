"""Running at sign-in: one value in the user's Run key, and Revert all removes it."""

from app.choices import Choice
from platform_win import startup
from platform_win.startup import FIX_ICONS_FLAG, RUN_KEY, VALUE_NAME, SignInRun
from tests.fakes import FakeDesktop, FakeUserRegistry


def test_switching_on_and_off_writes_one_run_value() -> None:
    registry = FakeUserRegistry()
    sign_in = SignInRun(registry, rf'"C:\Iconbloom\Iconbloom.exe" {FIX_ICONS_FLAG}')
    assert not sign_in.is_on()
    sign_in.set(True)
    assert sign_in.is_on()
    assert registry.values == {
        (RUN_KEY, VALUE_NAME): (1, r'"C:\Iconbloom\Iconbloom.exe" --fix-icons')
    }
    sign_in.set(False)
    sign_in.set(False)  # already off is fine
    assert registry.values == {}


def test_only_the_built_app_offers_it() -> None:
    assert startup.windows_sign_in_run() is None  # running from source: no exe to start


def test_revert_all_stops_the_sign_in_run(env: FakeDesktop) -> None:
    env.make("Paint")
    service = env.service()
    service.apply(service.scan()[0], Choice("kawaii_pink", "sticker"))
    env.sign_in.set(True)
    service.revert_all(dry_run=True)
    assert env.sign_in.is_on()
    service.revert_all()
    assert not env.sign_in.is_on()
