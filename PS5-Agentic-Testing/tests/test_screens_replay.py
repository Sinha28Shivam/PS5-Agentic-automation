"""Replay tests on REAL PS5 frames captured 2026-10-30 (tests/fixtures/frames).

Guards config/screens/*.yaml against regressions.
"""

from pathlib import Path

import cv2
import pytest

from ps5agent.perception import ocr, signatures

FRAMES = Path(__file__).parent / "fixtures" / "frames"

EXPECTED = {
    "home": "home", "home_media": "home_media", "control_center": "control_center",
    "search_empty": "search", "keyboard": "search_keyboard",
    "keyboard_typed": "search_keyboard", "search_results": "search_results",
    "settings": "settings", "settings_system_sel": "settings_system",
    "game_hub": "game_hub",
}

pytestmark = pytest.mark.skipif(not ocr.available(), reason="tesseract missing")


@pytest.fixture(autouse=True)
def _real_screens(monkeypatch):
    monkeypatch.setattr(signatures, "SCREENS_DIR",
                        Path(__file__).parents[1] / "config" / "screens", raising=False)
    signatures.clear_cache()
    yield
    signatures.clear_cache()


@pytest.mark.parametrize("frame,screen", sorted(EXPECTED.items()))
def test_screen_classified(frame, screen):
    text = ocr.read_text(cv2.imread(str(FRAMES / f"{frame}.jpg")))
    best = signatures.best(text)
    assert best is not None and best[0] == screen, signatures.match(text)[:3]


def test_home_is_not_a_store_screen():
    text = ocr.read_text(cv2.imread(str(FRAMES / "home.jpg")))
    assert signatures.danger_screen(text) is None


def test_cc_home_focus_detector():
    from ps5agent.hw.adapters import cc_home_focused
    assert cc_home_focused(cv2.imread(str(FRAMES / "cc_bar.jpg")))           # Home focused
    assert not cc_home_focused(cv2.imread(str(FRAMES / "cc_bar_left.jpg")))  # Power focused
    assert not cc_home_focused(cv2.imread(str(FRAMES / "home.jpg")))


def test_power_menu_is_recognised():
    text = ocr.read_text(cv2.imread(str(FRAMES / "power_menu.jpg")))
    assert signatures.best(text)[0] == "power_menu"
