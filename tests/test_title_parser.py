"""Title parser sanity tests. Run with: python -m pytest tests/

Aim: catch regressions in the parser when we add new parallel names or
players. These are the cases that have historically tripped up regex parsers
on eBay card titles.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.title_parser import parse


PLAYER_INDEX = {
    "junior caminero": "Junior Caminero",
    "roki sasaki":     "Roki Sasaki",
    "konnor griffin":  "Konnor Griffin",
    "kristian campbell": "Kristian Campbell",
}


def test_basic_psa10_refractor():
    p = parse("2023 Bowman Chrome Junior Caminero #BCP-100 Auto Refractor PSA 10", PLAYER_INDEX)
    assert p.year == 2023
    assert p.product == "Bowman Chrome"
    assert p.grade == "PSA 10"
    assert p.player == "Junior Caminero"
    assert p.parallel.name == "Refractor"
    assert p.rejected_reason is None


def test_gold_50_print_run():
    p = parse("JUNIOR CAMINERO 2023 Bowman Chrome PROSPECT AUTO RC GOLD /50 BGS 9.5", PLAYER_INDEX)
    assert p.parallel.name == "Gold Refractor /50"
    assert p.print_run == 50
    assert p.grade == "BGS 9.5"


def test_superfractor_one_of_one():
    p = parse("Roki Sasaki 2024 Bowman Chrome Sapphire Edition 1st Auto SUPERFRACTOR 1/1", PLAYER_INDEX)
    assert p.parallel.name == "Superfractor"
    assert p.parallel.tier == 1
    assert p.is_first_bowman is True


def test_bowman_draft_sky_blue():
    p = parse("2025 Bowman Draft Konnor Griffin BD-150 Chrome Prospect Auto Sky Blue /499", PLAYER_INDEX)
    assert p.product == "Bowman Draft"
    assert p.parallel.name == "Sky Blue Refractor"
    assert p.print_run == 499
    assert p.player == "Konnor Griffin"


def test_reject_sterling():
    p = parse("2023 Bowman Sterling Junior Caminero Auto PSA 10", PLAYER_INDEX)
    assert p.rejected_reason is not None
    assert "wrong product" in p.rejected_reason


def test_reject_sealed_box():
    p = parse("2024 Bowman Chrome Hobby Box Sealed", PLAYER_INDEX)
    assert p.rejected_reason is not None


def test_reject_non_auto():
    p = parse("2023 Bowman Chrome Junior Caminero #BCP-100 Refractor PSA 10", PLAYER_INDEX)
    assert p.rejected_reason == "not an autograph"


def test_reject_lot():
    p = parse("Lot of 5 Bowman Chrome Prospect Autos", PLAYER_INDEX)
    assert p.rejected_reason is not None


def test_raw_fallback():
    p = parse("2023 Bowman Chrome Junior Caminero Refractor Auto", PLAYER_INDEX)
    assert p.grade == "Raw"


def test_card_number_extraction():
    p = parse("2023 Bowman Chrome #CPA-JC Junior Caminero Auto Gold /50 PSA 10", PLAYER_INDEX)
    assert p.card_number == "CPA-JC"
    assert p.print_run == 50


def test_unknown_player_returns_none():
    p = parse("2023 Bowman Chrome Some Random Guy Auto Refractor PSA 10", PLAYER_INDEX)
    assert p.player is None
    # But not rejected — we may still want to surface unknowns for manual review.
    assert p.rejected_reason is None
