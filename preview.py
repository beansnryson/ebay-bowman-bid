"""Preview generator — runs the scoring pipeline against today's real auctions
with synthetic comp prices, so you can see what the report will look like
once the eBay Marketplace Insights API approval lands.

The comp values below are realistic estimates based on recent BCP market
prices but are NOT real sales data. They're labeled clearly as synthetic in
the output.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from src.db import connect
from src.parallel_tiers import match_parallel
from src.scoring import score, GRADE_WEIGHTS
from src.shill_detector import assess
from src.comps import CompSummary
from src.ebay_client import EbayListing
from src.title_parser import ParsedListing


# Realistic 90-day median comps for the cards we expect to see. Keyed by
# (player, year, parallel_name, grade). Values reflect mid-2025 BCP market.
SYNTHETIC_COMPS: dict[tuple, float] = {
    # Superfractors (1/1)
    ("Konnor Griffin",    2025, "Superfractor",       "Raw"):     85000,
    ("Konnor Griffin",    2024, "Superfractor",       "BGS 9.5"): 50000,
    ("Walker Jenkins",    2024, "Superfractor",       "Raw"):     60000,
    ("Walker Jenkins",    2024, "Superfractor",       "PSA 10"):  75000,
    ("Roki Sasaki",       2025, "Superfractor",       "PSA 10"):  50000,
    ("Max Clark",         2023, "Superfractor",       "PSA 10"):  45000,
    ("Dylan Crews",       2024, "Superfractor",       "Raw"):     40000,
    ("Jackson Holliday",  2023, "Superfractor",       "Raw"):     22000,
    ("Jackson Holliday",  2024, "Superfractor",       "Raw"):     14000,
    ("Termarr Johnson",   2023, "Superfractor",       "PSA 10"):   8500,
    # Red /5
    ("Jasson Dominguez",  2020, "Red Refractor /5",   "BGS 10"): 120000,
    ("James Wood",        2022, "Red Refractor /5",   "SGC 9.5"): 45000,
    ("Max Clark",         2023, "Red Refractor /5",   "PSA 9"):   25000,
    ("Termarr Johnson",   2023, "Red Refractor /5",   "PSA 10"):  28000,
    ("Termarr Johnson",   2022, "Red Refractor /5",   "PSA 10"):  12000,
    ("James Wood",        2025, "Red Refractor /5",   "PSA 9"):   17000,
    ("Ethan Salas",       2023, "Red Refractor /5",   "Raw"):     22000,
    ("Dylan Crews",       2025, "Red Refractor /5",   "Raw"):      8500,
    ("Roki Sasaki",       2025, "Red Refractor /5",   "Raw"):      4500,
    ("Jackson Chourio",   2023, "Red Refractor /5",   "PSA 10"):   3500,
    # Printing Plates (1/1)
    ("Druw Jones",        2023, "Printing Plate",     "PSA 10"):   1100,
    ("Konnor Griffin",    2024, "Printing Plate",     "Raw"):     12000,
    ("Konnor Griffin",    2024, "Printing Plate",     "PSA 10"):   7500,
    ("Bubba Chandler",    2021, "Printing Plate",     "Raw"):      4000,
    ("Dylan Crews",       2024, "Printing Plate",     "Raw"):      6000,
    # Tier 2 — Orange /25, Gold /50, Lava
    ("Andrew Painter",    2021, "Orange Refractor /25", "PSA 10"): 9500,
    ("Andrew Painter",    2021, "Lava Refractor",       "PSA 10"):  450,
    ("Andrew Painter",    2021, "Gold Refractor /50",   "PSA 9"):   850,
    ("Druw Jones",        2023, "Lava Refractor",       "PSA 10"): 1800,
    ("Dylan Crews",       2025, "Orange Refractor /25", "PSA 10"):  650,
    ("Ethan Salas",       2023, "Lava Refractor",       "PSA 10"): 4200,
    ("Jackson Holliday",  2022, "Lava Refractor",       "PSA 10"): 1300,
    ("Jackson Holliday",  2022, "Orange Refractor /25", "PSA 10"): 3800,
    ("James Wood",        2022, "Orange Refractor /25", "PSA 10"): 4200,
}


def build_population_comps(rows) -> dict[tuple, tuple[float, int]]:
    """Derive pseudo-comps from today's scan itself.

    For each (player, parallel_name) group with >=3 priced listings, take the
    median of grade-normalized current prices, then scale back up per grade at
    lookup time. Mid-auction prices run light, so apply a 1.25 final-price
    uplift. Synthetic — but player-aware, which a flat tier table isn't.
    """
    from statistics import median as _median
    groups: dict[tuple, list[float]] = {}
    for r in rows:
        price = r["current_price"]
        if not price or not r["player"] or not r["parallel_name"]:
            continue
        gw = GRADE_WEIGHTS.get(r["grade"], 0.7)
        groups.setdefault((r["player"], r["parallel_name"]), []).append(price / gw)
    return {
        k: (_median(v) * 1.25, len(v))
        for k, v in groups.items()
        if len(v) >= 3
    }


def synth_comp(pop_comps, player, year, parallel_name, grade) -> CompSummary:
    """Population-derived pseudo-comp first, hand-coded table as fallback."""
    hand = SYNTHETIC_COMPS.get((player, year, parallel_name, grade))
    pop = pop_comps.get((player, parallel_name))
    if pop:
        norm_median, n = pop
        median = norm_median * GRADE_WEIGHTS.get(grade, 0.7)
        sample = n
    elif hand:
        median, sample = hand, 8
    else:
        return CompSummary(None, 0, None, None, None)
    return CompSummary(
        median_price=median,
        sample_count=sample,
        high=median * 1.25,
        low=median * 0.75,
        most_recent_date=datetime.now(timezone.utc).date().isoformat(),
    )


def main():
    from src.title_parser import load_player_index
    player_index = load_player_index("data/checklist.csv")

    conn = connect()
    rows = conn.execute("""
        SELECT item_id, title, url, image_url, seller_feedback, seller_pos_pct,
               current_price, bid_count, end_time, listing_type,
               year, product, player, parallel_name, parallel_tier,
               print_run, grade, card_number, is_first_bowman, rejected_reason
        FROM auctions
        WHERE rejected_reason IS NULL AND player IS NOT NULL AND year IS NOT NULL
    """).fetchall()

    pop_comps = build_population_comps(rows)
    scored = []
    for r in rows:
        listing = EbayListing(
            item_id=r["item_id"], title=r["title"], url=r["url"],
            image_url=r["image_url"], seller_username=None,
            seller_feedback=r["seller_feedback"], seller_pos_pct=r["seller_pos_pct"],
            current_price=r["current_price"], bid_count=r["bid_count"],
            end_time=r["end_time"], listing_type=r["listing_type"],
        )
        parallel = match_parallel(r["title"]) if r["parallel_name"] else None
        # Re-detect grade from the title — the parser may have been fixed
        # since this row was scanned.
        from src.title_parser import _detect_grade
        parsed = ParsedListing(
            title=r["title"], year=r["year"], product=r["product"],
            player=r["player"], parallel=parallel, print_run=r["print_run"],
            grade=_detect_grade(r["title"]), card_number=r["card_number"],
            is_first_bowman=bool(r["is_first_bowman"]),
            rejected_reason=None,
        )
        comps = synth_comp(pop_comps, parsed.player, parsed.year, parsed.parallel.name if parsed.parallel else "", parsed.grade)
        shill = assess(listing, comps.median_price)
        scored.append(score(listing, parsed, comps, shill))

    # Score only auctions ending in the next 24h (the daily watchlist window).
    # The full week's scan population still feeds the comp pool above.
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    with_comps = [
        s for s in scored
        if s.comps.median_price is not None
        and s.listing.end_time
        and s.listing.end_time[:19] <= cutoff[:19]
    ]
    with_comps.sort(key=lambda s: s.score, reverse=True)

    # Player diversity cap
    seen: dict[str, int] = {}
    top: list = []
    for s in with_comps:
        k = s.parsed.player or "_"
        if seen.get(k, 0) >= 2:
            continue
        top.append(s); seen[k] = seen.get(k, 0) + 1
        if len(top) >= 20:
            break

    out = Path("reports/PREVIEW_with_comps.md")
    lines = [
        "# 🔮 PREVIEW — What the report will look like once Marketplace Insights API is approved",
        "",
        "*This report was generated from **today's actual eBay auctions** with **synthetic comp data** ",
        "stitched in to demonstrate the final UX. The 'Comp Median' column shows estimated 90-day medians ",
        "(not real sales) so you can see how the deal score and Max Bid suggestion will work.*",
        "",
        f"*Real auctions scanned: {len(rows)} · With synthetic comp matches: {len(with_comps)}*",
        "",
        "---",
        "",
        "| # | Card | Grade | Tier | Current | Comp Median | **Max Bid** | Score | Shill | Link |",
        "|---|------|-------|------|---------|-------------|-------------|-------|-------|------|",
    ]
    for i, s in enumerate(top, 1):
        card = f"{s.parsed.year} {s.parsed.product} {s.parsed.player} {s.parsed.parallel.name}"
        cur = f"${s.listing.current_price:,.0f}" if s.listing.current_price else "—"
        med = f"${s.comps.median_price:,.0f}"
        mx = f"${s.suggested_max_bid:,.0f}"
        emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}[s.shill.risk]
        lines.append(
            f"| {i} | {card} | {s.parsed.grade} | T{s.parsed.parallel.tier} "
            f"| {cur} | {med} | **{mx}** | {s.score:+.2f} | {emoji} | [view]({s.listing.url}) |"
        )

    lines += ["", "---", "", "## Detail (top 10)", ""]
    for i, s in enumerate(top[:10], 1):
        delta = s.comps.median_price - (s.listing.current_price or 0)
        delta_pct = delta / s.comps.median_price * 100
        verdict = "🟢 **DEAL** — currently below comp median" if delta > 0 else "🔴 **OVERPRICED** — currently above comp median"

        # Sanity flags — a score this good usually means the listing isn't
        # what the parser thinks it is. Surface that instead of hiding it.
        cautions = []
        price = s.listing.current_price or 0
        if price and price < s.comps.median_price * 0.25:
            cautions.append(
                "price is <25% of comp median — verify the listing photos/description; "
                "this is usually a damaged card, a reprint, a different parallel, or a comp mismatch"
            )
        others = [
            canonical for key, canonical in player_index.items()
            if canonical != s.parsed.player and key in s.parsed.title.lower()
        ]
        if others:
            cautions.append(
                f"title also mentions {', '.join(others)} — may be a dual auto or multi-card listing; comp may not apply"
            )
        lines += [
            f"### {i}. {s.listing.title}",
            "",
            f"- **Verdict:** {verdict} (delta: ${delta:+,.0f} / {delta_pct:+.1f}%)",
            f"- **Comp basis:** ${s.comps.median_price:,.0f} median across {s.comps.sample_count} recent sales (range ${s.comps.low:,.0f}–${s.comps.high:,.0f})",
            f"- **Suggested max bid:** **${s.suggested_max_bid:,.0f}** ({(s.suggested_max_bid/s.comps.median_price - 1)*100:+.0f}% vs comp median)",
            f"- **Rarity weight:** {s.rarity_weight:.1f}× ({s.parsed.parallel.name}, tier {s.parsed.parallel.tier})",
            f"- **Grade weight:** {s.grade_weight:.2f}× ({s.parsed.grade})",
            f"- **Seller:** feedback {s.listing.seller_feedback}, {s.listing.seller_pos_pct}% positive",
        ]
        if s.shill.reasons:
            lines.append(f"- **⚠️ Shill flags:** " + "; ".join(s.shill.reasons))
        for c in cautions:
            lines.append(f"- **🚨 Verify before bidding:** {c}")
        lines += [f"- **eBay:** {s.listing.url}", ""]

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out} ({len(top)} cards)")


if __name__ == "__main__":
    main()
