"""Shill bidding heuristics.

eBay anonymizes bidder IDs (b***r format) so we can't conclusively identify
a shill. What we *can* do: flag listings where the bid pattern, seller
profile, or price velocity looks suspicious enough to warrant caution.

Returns a risk level + the reasons. Used to discount scores or warn the user.
"""

from dataclasses import dataclass
from typing import Optional

from src.ebay_client import EbayListing


@dataclass
class ShillAssessment:
    risk: str           # 'low' | 'medium' | 'high'
    reasons: list[str]


def assess(listing: EbayListing, comp_median: Optional[float]) -> ShillAssessment:
    reasons: list[str] = []

    # Seller heuristics
    if listing.seller_feedback is not None and listing.seller_feedback < 25:
        reasons.append(f"Low-feedback seller ({listing.seller_feedback})")

    if listing.seller_pos_pct is not None and listing.seller_pos_pct < 98.0:
        reasons.append(f"Sub-98% positive feedback ({listing.seller_pos_pct}%)")

    # Bid velocity vs price — too many bids on a low-feedback seller is a
    # classic shill pattern (the seller's alts driving the price up).
    if (
        listing.bid_count is not None
        and listing.bid_count > 15
        and (listing.seller_feedback or 0) < 50
    ):
        reasons.append(
            f"{listing.bid_count} bids on a low-feedback seller — possible bid stacking"
        )

    # Current price already above comp median is suspicious mid-auction.
    if (
        comp_median is not None
        and listing.current_price is not None
        and listing.current_price > comp_median * 1.25
        and listing.bid_count
        and listing.bid_count > 5
    ):
        reasons.append(
            f"Current bid {listing.current_price:.0f} exceeds 90-day median "
            f"{comp_median:.0f} by >25%"
        )

    # Risk tiering
    if any("bid stacking" in r or "Sub-98%" in r for r in reasons):
        risk = "high"
    elif len(reasons) >= 2:
        risk = "high"
    elif reasons:
        risk = "medium"
    else:
        risk = "low"

    return ShillAssessment(risk=risk, reasons=reasons)
