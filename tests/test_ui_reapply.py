"""Putting back, at start, the styles an app update reset (Chrome does at every update)."""

from app.service import Status
from tests.ui_harness import Harness, button


def test_icons_an_update_reset_are_put_back_at_start(harness: Harness) -> None:
    harness.style("Arcade")
    harness.update_resets(harness.lnk("Arcade"))

    window = harness.reopen()
    harness.qtbot.waitUntil(lambda: harness.status("Arcade") is Status.THEMED, timeout=10_000)
    assert window.reapply_box.isChecked()  # on unless switched off
    assert "Put back 1 icon an app update had reset." in window.statusBar().currentMessage()
    window.close()


def test_switching_it_off_sticks_and_leaves_reset_icons(harness: Harness) -> None:
    harness.style("Arcade")
    harness.window.reapply_box.setChecked(False)
    harness.update_resets(harness.lnk("Arcade"))

    window = harness.reopen()
    assert not window.reapply_box.isChecked()
    assert harness.status("Arcade") is Status.NEEDS_REAPPLY
    window.close()


def test_shared_shortcuts_are_offered_not_changed(harness: Harness) -> None:
    harness.style("Admin Tool")
    harness.update_resets(harness.desktop.common / "Admin Tool.lnk")

    window = harness.reopen()
    # No permission prompt nobody asked for: just an offer.
    assert "every user on this PC shares" in window.notice.label.text()
    assert harness.status("Admin Tool") is Status.NEEDS_REAPPLY

    window.settings.shared_shortcuts = "include"  # answer the prompt the button brings up
    button(window.notice, "Put back").click()
    harness.qtbot.waitUntil(lambda: harness.status("Admin Tool") is Status.THEMED, timeout=10_000)
    window.close()


def test_fix_at_sign_in_is_off_until_ticked_and_revert_all_unticks_it(
    harness: Harness, say_yes: None
) -> None:
    window = harness.window
    action = window.sign_in_action
    assert action.isVisible()
    assert not action.isChecked()  # off by default
    action.trigger()
    assert harness.desktop.sign_in.is_on()

    window.revert_all()
    harness.settle()
    assert not harness.desktop.sign_in.is_on()
    assert not action.isChecked()


def test_after_putting_icons_back_it_offers_to_do_that_by_itself(harness: Harness) -> None:
    harness.style("Arcade")
    harness.update_resets(harness.lnk("Arcade"))

    window = harness.reopen()
    harness.qtbot.waitUntil(lambda: harness.status("Arcade") is Status.THEMED, timeout=10_000)
    assert "by itself from now on" in window.notice.label.text()
    button(window.notice, "Fix automatically").click()
    assert harness.desktop.sign_in.is_on()
    assert window.sign_in_action.isChecked()
    assert harness.desktop.keeper_starts == 1  # running now, not from the next sign-in
    window.close()


def test_not_now_means_the_offer_isnt_made_again(harness: Harness) -> None:
    harness.style("Arcade")
    harness.update_resets(harness.lnk("Arcade"))
    window = harness.reopen()
    harness.qtbot.waitUntil(lambda: harness.status("Arcade") is Status.THEMED, timeout=10_000)
    button(window.notice, "Not now").click()

    harness.update_resets(harness.lnk("Arcade"))
    window = harness.reopen()
    harness.qtbot.waitUntil(lambda: harness.status("Arcade") is Status.THEMED, timeout=10_000)
    assert not window.notice.isVisible()
    assert not harness.desktop.sign_in.is_on()
    window.close()


def test_opening_iconbloom_starts_keeping_icons_when_it_is_on(harness: Harness) -> None:
    harness.desktop.sign_in.set(True)
    starts = harness.desktop.keeper_starts
    window = harness.reopen()
    assert harness.desktop.keeper_starts == starts + 1  # after an update stopped it, say
    window.close()
