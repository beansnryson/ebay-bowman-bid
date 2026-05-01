"""Parse messy eBay listing titles for Bowman 1st autographed cards.

Extracts: year, product (Bowman / Bowman Chrome / Bowman Draft), parallel,
print run /N, grade (PSA/SGC/BGS or raw), card number, and player name.

Listing titles vary wildly. Examples we need to handle:
  "2023 Bowman Chrome Junior Caminero #BCP-100 Auto Refractor PSA 10"
  "JUNIOR CAMINERO 2023 Bowman Chrome PROSPECT AUTO RC GOLD /50 BGS 9.5"
  "Roki Sasaki 2024 Bowman Chrome Sapphire Edition 1st Auto SUPERFRACTOR 1/1"
  "2025 Bowman Draft Konnor Griffin BD-150 Chrome Prospect Auto Sky Blue /499"

Strategy:
  1. Reject anything that isn't a 1st Bowman auto (no Sterling/Best/Inception/etc).
  2. Reject sealed boxes, breaks, and lots — we want single-card auctions only.
  3. Pull year, product, grade, parallel, print run with regex.
  4. Match player name against the checklist (loaded once at startup).
"""

import re
from dataclasses import dataclass
from typing import Optional

from src.parallel_tiers import Parallel, match_parallel


# Products we accept (Bowman Chrome / Bowman Draft / Bowman flagship only).
ACCEPT_PATTERNS = [
    r"\bbowman\s+chrome\b",
    r"\bbowman\s+draft\b",
    r"\bbowman\b(?!\s+(?:sterling|best|inception|platinum|heritage|sapphire))",
]
# Bowman Sapphire is a Bowman Chrome variant — accept if "Chrome" also present.

# Hard rejects — wrong product line.
REJECT_PRODUCTS = [
    r"\bbowman\s+sterling\b",
    r"\bbowman'?s?\s+best\b",
    r"\bbowman\s+inception\b",
    r"\bbowman\s+platinum\b",
    r"\bbowman\s+heritage\b",
    r"\btopps\s+chrome\b",
    r"\bfinest\b",
]

# Reject non-card listings.
REJECT_NONCARD = [
    r"\b(?:sealed|hobby\s+box|jumbo|blaster|mega\s+box|cello|fat\s+pack)\b",
    r"\b(?:case|break|spot|random\s+team|pyt)\b",
    r"\b(?:lot\s+of|\d+\s+card\s+lot|bulk)\b",
    r"\bcomplete\s+set\b",
]

# Must be an autograph (this is a 1st Bowman AUTO scanner).
AUTO_REQUIRED = [
    r"\bauto(?:graph)?s?\b",
    r"\bsigned\b",
    r"\b1st\s+bowman\s+auto\b",
]

YEAR_RE = re.compile(r"\b(20\d{2})\b")
PRINT_RUN_RE = re.compile(r"/\s*(\d{1,4})\b")
CARD_NUM_RE = re.compile(r"#\s*([A-Z]{2,5}-?[A-Z0-9]+)", re.IGNORECASE)

GRADE_PATTERNS = [
    (re.compile(r"\bPSA\s*10\b", re.I),         "PSA 10"),
    (re.compile(r"\bPSA\s*9(?!\.\d)\b", re.I),  "PSA 9"),
    (re.compile(r"\bPSA\s*9\.5\b", re.I),       "PSA 9.5"),
    (re.compile(r"\bPSA\s*8\b", re.I),          "PSA 8"),
    (re.compile(r"\bBGS\s*10\b", re.I),         "BGS 10"),
    (re.compile(r"\bBGS\s*9\.5\b", re.I),       "BGS 9.5"),
    (re.compile(r"\bBGS\s*9\b", re.I),          "BGS 9"),
    (re.compile(r"\bSGC\s*10\b", re.I),         "SGC 10"),
    (re.compile(r"\bSGC\s*9\.5\b", re.I),       "SGC 9.5"),
    (re.compile(r"\bSGC\s*9\b", re.I),          "SGC 9"),
    (re.compile(r"\bCGC\s*10\b", re.I),         "CGC 10"),
    (re.compile(r"\bCGC\s*9\.5\b", re.I),       "CGC 9.5"),
]


@dataclass
class ParsedListing:
    title: str
    year: Optional[int]
    product: Optional[str]      # "Bowman Chrome" | "Bowman Draft" | "Bowman"
    player: Optional[str]
    parallel: Optional[Parallel]
    print_run: Optional[int]    # numbered /N, or None for unnumbered
    grade: str                  # "PSA 10" | "PSA 9" | ... | "Raw"
    card_number: Optional[str]
    is_first_bowman: bool       # explicit "1st Bowman" mention
    rejected_reason: Optional[str] = None  # set if listing should be skipped


def _detect_product(title: str) -> Optional[str]:
    t = title.lower()
    if re.search(r"\bbowman\s+chrome\b", t) or re.search(r"\bbowman\s+sapphire\b", t):
        return "Bowman Chrome"
    if re.search(r"\bbowman\s+draft\b", t):
        return "Bowman Draft"
    if re.search(r"\bbowman\b", t):
        return "Bowman"
    return None


def _detect_grade(title: str) -> str:
    for pattern, label in GRADE_PATTERNS:
        if pattern.search(title):
            return label
    return "Raw"


def _is_rejected(title: str) -> Optional[str]:
    t = title.lower()
    for pat in REJECT_PRODUCTS:
        if re.search(pat, t):
            return f"wrong product line ({pat})"
    for pat in REJECT_NONCARD:
        if re.search(pat, t):
            return "non-single-card listing"
    if not any(re.search(p, t) for p in AUTO_REQUIRED):
        return "not an autograph"
    if not any(re.search(p, t) for p in ACCEPT_PATTERNS):
        return "not Bowman / Bowman Chrome / Bowman Draft"
    return None


def parse(title: str, player_index: dict[str, str]) -> ParsedListing:
    """Parse a listing title.

    `player_index` maps lowercased player name → canonical name (from checklist).
    Used to detect which prospect the listing is for.
    """
    rejection = _is_rejected(title)

    year_m = YEAR_RE.search(title)
    year = int(year_m.group(1)) if year_m else None

    product = _detect_product(title)
    grade = _detect_grade(title)
    parallel = match_parallel(title)

    run_m = PRINT_RUN_RE.search(title)
    print_run = int(run_m.group(1)) if run_m else None
    # If the matched parallel has a known print run and we didn't pull one, use it.
    if print_run is None and parallel.print_run > 0:
        print_run = parallel.print_run

    num_m = CARD_NUM_RE.search(title)
    card_number = num_m.group(1).upper() if num_m else None

    is_first_bowman = bool(re.search(r"\b1st\s+(?:bowman|auto)\b", title, re.I))

    player = _match_player(title, player_index)

    return ParsedListing(
        title=title,
        year=year,
        product=product,
        player=player,
        parallel=parallel,
        print_run=print_run,
        grade=grade,
        card_number=card_number,
        is_first_bowman=is_first_bowman,
        rejected_reason=rejection,
    )


def _match_player(title: str, player_index: dict[str, str]) -> Optional[str]:
    """Find the longest player name that appears in the title.

    Longest-match wins so 'Junior Caminero Jr' beats 'Junior'.
    """
    t = title.lower()
    best = None
    best_len = 0
    for key, canonical in player_index.items():
        if len(key) > best_len and key in t:
            best = canonical
            best_len = len(key)
    return best


def load_player_index(checklist_path: str) -> dict[str, str]:
    """Load player names from a CSV with a 'player_name' column."""
    import csv
    index = {}
    with open(checklist_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row.get("player_name", "").strip()
            if name:
                index[name.lower()] = name
    return index
