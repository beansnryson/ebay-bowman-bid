"""Score auctions and suggest a max bid.

Score formula:
    score = (comp_median - current_price) / comp_median * rarity * grade * shill_factor

Higher score = better deal. Negative = currently overpriced vs comps.

Suggested max bid:
    max_bid = comp_median * (0.85 + grade_bonus) * rarity_floor
The 0.85 base means we're targeting at least 15% under comp median to beat the
hidden cost of fees + slab risk + opportunity cost.
"""

from dataclasses import dataclass
from typing import Optional

from src.comps import CompSummary
from src.ebay_client import EbayListing
from src.shill_detector import ShillAssessment
from src.title_parser import ParsedListing


GRADE_WEIGHTS = {
    "PSA 10":  1.5,
    "BGS 10":  1.5,
    "SGC 10":  1.4,
    "PSA 9.5": 1.2,
    "BGS 9.5": 1.2,
    "SGC 9.5": 1.15,
    "PSA 9":   1.0,
    "BGS 9":   1.0,
    "SGC 9":   0.95,
    "PSA 8":   0.75,
    "PSA 8.5": 0.8,
    "PSA 7":   0.55,
    "PSA 6":   0.45,
    "Raw":     0.7,
}

GRADE_MAX_BID_BONUS = {
    "PSA 10":  0.10,
    "BGS 10":  0.10,
    "SGC 10":  0.05,
    "PSA 9.5": 0.05,
    "PSA 9":   0.0,
    "Raw":    -0.10,
}

SHILL_FACTOR = {"low": 1.0, "medium": 0.85, "high": 0.5}


@dataclass
class ScoredAuction:
    listing: EbayListing
    parsed: ParsedListing
    comps: CompSummary
    shill: ShillAssessment
    score: float
    suggested_max_bid: Optional[float]
    rarity_weight: float
    grade_weight: float
    rationale: str


def score(
    listing: EbayListing,
    parsed: ParsedListing,
    comps: CompSummary,
    shill: ShillAssessment,
) -> ScoredAuction:
    rarity_weight = parsed.parallel.weight if parsed.parallel else 1.0
    grade_weight = GRADE_WEIGHTS.get(parsed.grade, 0.7)
    shill_factor = SHILL_FACTOR.get(shill.risk, 1.0)

    if comps.median_price and listing.current_price:
        delta_pct = (comps.median_price - listing.current_price) / comps.median_price
        raw_score = delta_pct * rarity_weight * grade_weight * shill_factor
    else:
        # No comps: rank purely by intrinsic value (rarity × grade × shill).
        # Scaled to fall in the same range as deal scores so they sort sensibly.
        # PSA 10 Superfractor: 0.30, raw base auto: 0.06.
        raw_score = (rarity_weight * grade_weight * shill_factor) / 15.0

    suggested_max = None
    if comps.median_price:
        bonus = GRADE_MAX_BID_BONUS.get(parsed.grade, 0.0)
        # Rarity bumps the ceiling slightly — willing to pay more for tier 1/2.
        rarity_floor = 1.0 + (0.05 * (5 - parsed.parallel.tier)) if parsed.parallel else 1.0
        suggested_max = round(comps.median_price * (0.85 + bonus) * rarity_floor, 2)

    rationale = _build_rationale(parsed, comps, listing, shill, suggested_max)

    return ScoredAuction(
        listing=listing,
        parsed=parsed,
        comps=comps,
        shill=shill,
        score=raw_score,
        suggested_max_bid=suggested_max,
        rarity_weight=rarity_weight,
        grade_weight=grade_weight,
        rationale=rationale,
    )


def _build_rationale(parsed, comps, listing, shill, suggested_max) -> str:
    parts = []
    if comps.median_price:
        parts.append(
            f"90-day median ${comps.median_price:,.0f} (n={comps.sample_count}); "
            f"currently at ${listing.current_price:,.0f}"
        )
    else:
        parts.append("No comps found — proceed with caution")
    if parsed.parallel and parsed.parallel.tier <= 2:
        parts.append(f"Rarity bump: {parsed.parallel.name} (tier {parsed.parallel.tier})")
    if parsed.grade in ("PSA 10", "BGS 10"):
        parts.append(f"Grade bump: {parsed.grade}")
    if shill.risk != "low":
        parts.append(f"⚠️ Shill risk {shill.risk}: " + "; ".join(shill.reasons))
    if suggested_max:
        parts.append(f"Max bid suggestion: ${suggested_max:,.0f}")
    return " · ".join(parts)
