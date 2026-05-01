"""Parallel rarity tier map for Bowman 1st autographed cards.

Tiers drive the scoring weight: rarer parallels get more weight in the daily
shortlist. Numbers reflect typical print runs for modern Bowman Chrome /
Bowman Draft / Bowman flagship.

Ordering inside each tier matters for matching: longer, more specific names
must come before shorter ones (e.g. "Superfractor" before "Refractor").
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Parallel:
    name: str           # canonical name
    tier: int           # 1 = rarest (1/1), 4 = most common
    print_run: int      # 0 = unnumbered, otherwise the /N
    weight: float       # scoring multiplier
    aliases: tuple      # alternate spellings seen on eBay

# Tier 1 — 1/1 or near-1/1
TIER_1 = [
    Parallel("Superfractor",           1, 1,   3.0, ("super fractor", "superfractor 1/1", "1/1 superfractor")),
    Parallel("Printing Plate",         1, 1,   2.5, ("plate", "printing plate cyan", "printing plate magenta", "printing plate yellow", "printing plate black")),
    Parallel("Red Refractor /5",       1, 5,   2.5, ("red ref /5", "red /5", "red refractor")),
]

# Tier 2 — rare numbered
TIER_2 = [
    Parallel("Orange Refractor /25",   2, 25,  2.0, ("orange ref /25", "orange /25", "orange refractor")),
    Parallel("Gold Refractor /50",     2, 50,  1.8, ("gold ref /50", "gold /50", "gold refractor")),
    Parallel("Atomic Refractor /99",   2, 99,  1.7, ("atomic ref", "atomic refractor", "atomic /99")),
    Parallel("Lava Refractor",         2, 25,  2.0, ("lava ref", "lava refractor")),
    Parallel("Speckle Refractor",      2, 50,  1.8, ("speckle ref", "speckle refractor")),
    Parallel("Mojo Refractor /99",     2, 99,  1.6, ("mojo ref", "mojo refractor", "mojo /99")),
]

# Tier 3 — mid-numbered
TIER_3 = [
    Parallel("Blue Refractor /150",    3, 150, 1.4, ("blue ref /150", "blue /150", "blue refractor")),
    Parallel("Green Refractor /99",    3, 99,  1.5, ("green ref", "green refractor", "green /99")),
    Parallel("Purple Refractor /250",  3, 250, 1.3, ("purple ref", "purple refractor", "purple /250")),
    Parallel("Aqua Refractor /125",    3, 125, 1.4, ("aqua ref", "aqua refractor", "aqua /125")),
    Parallel("Yellow Refractor /75",   3, 75,  1.5, ("yellow ref", "yellow refractor", "yellow /75")),
    Parallel("Sparkle Refractor",      3, 0,   1.4, ("sparkle ref", "sparkle refractor")),
]

# Tier 4 — common
TIER_4 = [
    Parallel("Sky Blue Refractor",     4, 0,   1.1, ("sky blue ref", "sky blue refractor", "sky blue")),
    Parallel("Refractor",              4, 0,   1.0, ("ref", "chrome refractor")),
    Parallel("Base Auto",              4, 0,   0.9, ("base", "base autograph", "1st bowman auto")),
]

ALL_PARALLELS = TIER_1 + TIER_2 + TIER_3 + TIER_4


def match_parallel(title: str) -> Parallel:
    """Find the best parallel match for an eBay listing title.

    Searches longest/most-specific names first so 'Superfractor' beats 'Refractor'.
    Returns Tier 4 'Base Auto' as fallback if no refractor terms found.
    """
    title_lower = title.lower()
    for p in ALL_PARALLELS:
        candidates = [p.name.lower()] + [a.lower() for a in p.aliases]
        for c in sorted(candidates, key=len, reverse=True):
            if c in title_lower:
                return p
    return ALL_PARALLELS[-1]  # Base Auto


def tier_weight(tier: int) -> float:
    """Aggregate weight bump per tier — used when print run is unknown."""
    return {1: 2.5, 2: 1.8, 3: 1.4, 4: 1.0}[tier]
