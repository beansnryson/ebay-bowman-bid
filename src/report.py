"""Markdown daily report generator."""

from datetime import datetime, timezone
from pathlib import Path

from src.scoring import ScoredAuction


REPORT_DIR = Path(__file__).parent.parent / "reports"


def write_report(scored: list[ScoredAuction], top_n: int = 20, max_per_player: int = 2) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    out = REPORT_DIR / f"daily_{today}.md"

    # Sort by score, then enforce per-player cap for diversity in top N.
    sorted_all = sorted(scored, key=lambda s: s.score, reverse=True)
    ranked: list[ScoredAuction] = []
    seen_count: dict[str, int] = {}
    for s in sorted_all:
        key = s.parsed.player or "_unknown"
        if seen_count.get(key, 0) >= max_per_player:
            continue
        ranked.append(s)
        seen_count[key] = seen_count.get(key, 0) + 1
        if len(ranked) >= top_n:
            break

    lines = [
        f"# Bowman 1st Auto — Auction Watchlist · {today}",
        "",
        f"*Top {len(ranked)} auctions ending in the next 24 hours, ranked by deal score "
        f"(comp delta × rarity × grade × shill factor).*",
        "",
        "---",
        "",
        "| # | Card | Grade | Tier | Current | Comp Median | Max Bid | Score | Shill | Link |",
        "|---|------|-------|------|---------|-------------|---------|-------|-------|------|",
    ]

    for i, s in enumerate(ranked, 1):
        card = f"{s.parsed.year or '?'} {s.parsed.product or '?'} {s.parsed.player or 'Unknown'} {s.parsed.parallel.name if s.parsed.parallel else ''}"
        comp_str = f"${s.comps.median_price:,.0f} (n={s.comps.sample_count})" if s.comps.median_price else "—"
        max_str = f"${s.suggested_max_bid:,.0f}" if s.suggested_max_bid else "—"
        cur_str = f"${s.listing.current_price:,.0f}" if s.listing.current_price else "—"
        link = f"[view]({s.listing.url})" if s.listing.url else ""
        shill_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(s.shill.risk, "⚪")
        lines.append(
            f"| {i} | {card} | {s.parsed.grade} | T{s.parsed.parallel.tier if s.parsed.parallel else '?'} "
            f"| {cur_str} | {comp_str} | **{max_str}** | {s.score:+.2f} | {shill_emoji} {s.shill.risk} | {link} |"
        )

    lines += ["", "---", "", "## Detail", ""]
    for i, s in enumerate(ranked, 1):
        lines += [
            f"### {i}. {s.listing.title}",
            "",
            f"- **Ends:** {s.listing.end_time}",
            f"- **Seller:** {s.listing.seller_username} (feedback {s.listing.seller_feedback}, {s.listing.seller_pos_pct}%)",
            f"- **Bids:** {s.listing.bid_count}",
            f"- **Rationale:** {s.rationale}",
        ]
        if s.shill.reasons:
            lines.append(f"- **Shill flags:** " + "; ".join(s.shill.reasons))
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out
