"""Replay tests on REAL PS5 frames captured 2026-10-30 (tests/fixtures/frames).

Guards config/screens/*.yaml and the MK11 HUD reader against regressions.
"""

from pathlib import Path

import cv2
import pytest
import yaml

from ps5agent.perception import ocr, signatures
from ps5agent.perception.hud import read_hud

FRAMES = Path(__file__).parent / "fixtures" / "frames"
PROFILE = yaml.safe_load((Path(__file__).parents[1] / "config" / "games" / "mk11" /
                          "profile.yaml").read_text(encoding="utf-8"))

EXPECTED = {
    "home": "home", "home_media": "home_media", "control_center": "control_center",
    "search_empty": "search", "keyboard": "search_keyboard",
    "keyboard_typed": "search_keyboard", "search_results": "search_results",
    "settings": "settings", "settings_system_sel": "settings_system",
    "mk11_hub_playbtn": "game_hub", "mk11_after_title2": "mk11_setup",
    "mk11_setup3": "mk11_main_menu", "mk11_fight_menu": "mk11_fight_menu",
    "mk11_local": "mk11_dialog", "mk11_local_menu2": "mk11_dialog",
    "mk11_local_list": "mk11_char_select", "mk11_after_cs": "mk11_char_select",
    "mk11_stage": "mk11_stage_select", "mk11_pause_real": "mk11_pause",
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


@pytest.mark.parametrize("frame,in_fight,p1,p2", [
    ("mk11_hud", 1.0, 0.634, 1.0),
    ("mk11_hud_after_combo", 1.0, 0.37, 0.859),
    ("mk11_spear", 1.0, 1.0, 0.992),
    ("mk11_fight_live", 0.0, 0.0, 0.0),        # intro cinematic
    ("mk11_pause_real", 0.0, 0.0, 0.0),
    ("home", 0.0, 0.0, 0.0),
])
def test_mk11_hud(frame, in_fight, p1, p2):
    h = read_hud(cv2.imread(str(FRAMES / f"{frame}.jpg")), PROFILE)
    assert h["in_fight"] == in_fight
    assert h["p1_health"] == pytest.approx(p1, abs=0.02)
    assert h["p2_health"] == pytest.approx(p2, abs=0.02)


def test_cc_home_focus_detector():
    from ps5agent.hw.adapters import cc_home_focused
    assert cc_home_focused(cv2.imread(str(FRAMES / "cc_bar.jpg")))           # Home focused
    assert not cc_home_focused(cv2.imread(str(FRAMES / "cc_bar_left.jpg")))  # Power focused
    assert not cc_home_focused(cv2.imread(str(FRAMES / "home.jpg")))


def test_power_menu_is_recognised():
    text = ocr.read_text(cv2.imread(str(FRAMES / "power_menu.jpg")))
    assert signatures.best(text)[0] == "power_menu"
