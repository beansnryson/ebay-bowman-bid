"""Main entrypoint — daily auction scan.

Usage:
    python -m src.scan              # live mode (needs eBay credentials)
    python -m src.scan --mock       # use canned sample data
    python -m src.scan --top 30     # change shortlist size
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import comps, db, report, scoring, shill_detector, title_parser
from src.ebay_client import EbayClient, MockEbayClient


CHECKLIST_PATH = Path(__file__).parent.parent / "data" / "checklist.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="use canned sample listings")
    ap.add_argument("--top", type=int, default=20, help="shortlist size")
    ap.add_argument("--hours", type=int, default=24, help="auction end window")
    args = ap.parse_args()

    if not CHECKLIST_PATH.exists():
        print(f"ERROR: {CHECKLIST_PATH} missing — see README for format.", file=sys.stderr)
        sys.exit(1)

    player_index = title_parser.load_player_index(str(CHECKLIST_PATH))
    print(f"Loaded {len(player_index)} players from checklist")

    # canonical names for targeted search (in original case)
    players = sorted(set(player_index.values()))

    client = MockEbayClient() if args.mock else EbayClient()
    conn = db.connect()

    scored: list[scoring.ScoredAuction] = []
    skipped = 0
    seen_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    print(f"Searching eBay for ending auctions across {len(players)} players...", flush=True)
    search_kwargs = {"hours_ahead": args.hours}
    if not args.mock:
        search_kwargs["players"] = players
    for listing in client.search_ending_soon(**search_kwargs):
        seen_count += 1
        if seen_count % 25 == 0:
            print(f"  ...processed {seen_count} listings, {len(scored)} scored, {skipped} skipped", flush=True)
        parsed = title_parser.parse(listing.title, player_index)

        # Persist the auction regardless — useful for historical analysis
        db.upsert_auction(conn, {
            "item_id": listing.item_id,
            "title": listing.title,
            "url": listing.url,
            "image_url": listing.image_url,
            "seller_feedback": listing.seller_feedback,
            "seller_pos_pct": listing.seller_pos_pct,
            "current_price": listing.current_price,
            "bid_count": listing.bid_count,
            "end_time": listing.end_time,
            "listing_type": listing.listing_type,
            "year": parsed.year,
            "product": parsed.product,
            "player": parsed.player,
            "parallel_name": parsed.parallel.name if parsed.parallel else None,
            "parallel_tier": parsed.parallel.tier if parsed.parallel else None,
            "print_run": parsed.print_run,
            "grade": parsed.grade,
            "card_number": parsed.card_number,
            "is_first_bowman": int(parsed.is_first_bowman),
            "first_seen": now_iso,
            "last_seen": now_iso,
            "rejected_reason": parsed.rejected_reason,
        })

        if parsed.rejected_reason or not parsed.player or not parsed.year:
            skipped += 1
            continue

        comp_summary = comps.lookup(
            conn,
            player=parsed.player,
            year=parsed.year,
            product=parsed.product or "",
            parallel_name=parsed.parallel.name if parsed.parallel else "",
            grade=parsed.grade,
        )
        shill = shill_detector.assess(listing, comp_summary.median_price)
        scored_auction = scoring.score(listing, parsed, comp_summary, shill)
        scored.append(scored_auction)

        # Persist score
        import json
        db.insert_score(conn, {
            "item_id": listing.item_id,
            "scored_at": now_iso,
            "comp_median": comp_summary.median_price,
            "comp_count": comp_summary.sample_count,
            "suggested_max_bid": scored_auction.suggested_max_bid,
            "score": scored_auction.score,
            "rarity_weight": scored_auction.rarity_weight,
            "grade_weight": scored_auction.grade_weight,
            "shill_risk": shill.risk,
            "shill_reasons": json.dumps(shill.reasons),
            "rationale": scored_auction.rationale,
        })

    conn.commit()
    conn.close()

    out = report.write_report(scored, top_n=args.top)
    print(f"Scored {len(scored)} auctions, skipped {skipped}")
    print(f"Report → {out}")


if __name__ == "__main__":
    main()
