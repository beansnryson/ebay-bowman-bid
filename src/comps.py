"""Historical sale comp lookup.

Primary source: 130point.com — aggregates eBay sold listings, no auth, public.
Fallback: cached comps stored in our local `comps` table.

We cache aggressively — comp prices don't change minute-to-minute, and 130point
does throttle. Default TTL: 24h per (player, year, parallel, grade) tuple.
"""

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Optional
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from src.db import insert_comp


COMP_TTL_SECONDS = 24 * 3600
USER_AGENT = "Mozilla/5.0 (compatible; ebay-bowman-bid/0.1)"


@dataclass
class CompSummary:
    median_price: Optional[float]
    sample_count: int
    high: Optional[float]
    low: Optional[float]
    most_recent_date: Optional[str]


def lookup(
    conn: sqlite3.Connection,
    player: str,
    year: int,
    product: str,
    parallel_name: str,
    grade: str,
) -> CompSummary:
    """Find recent comps. Hits cache first, falls back to 130point.com."""
    cached = _from_cache(conn, player, year, parallel_name, grade)
    if cached.sample_count >= 3:
        return cached

    fresh = _fetch_130point(player, year, product, parallel_name, grade)
    for sale in fresh:
        insert_comp(conn, {
            "player": player,
            "year": year,
            "product": product,
            "parallel_name": parallel_name,
            "grade": grade,
            "sale_price": sale["price"],
            "sale_date": sale["date"],
            "source": "130point",
            "source_url": sale.get("url"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    conn.commit()

    return _from_cache(conn, player, year, parallel_name, grade)


def _from_cache(conn, player, year, parallel_name, grade) -> CompSummary:
    rows = conn.execute(
        """
        SELECT sale_price, sale_date FROM comps
        WHERE player = ? AND year = ? AND parallel_name = ? AND grade = ?
        ORDER BY sale_date DESC
        LIMIT 25
        """,
        (player, year, parallel_name, grade),
    ).fetchall()
    if not rows:
        return CompSummary(None, 0, None, None, None)
    prices = [r[0] for r in rows]
    return CompSummary(
        median_price=median(prices),
        sample_count=len(prices),
        high=max(prices),
        low=min(prices),
        most_recent_date=rows[0][1],
    )


def _fetch_130point(player, year, product, parallel_name, grade) -> list[dict]:
    """Scrape recent sales from 130point.com.

    130point's search page accepts a free-form query and returns recent eBay
    sold listings. We build a query and parse the result table.
    """
    query_parts = [str(year), product, player, parallel_name, grade]
    query = " ".join(p for p in query_parts if p and p != "Raw")
    url = "https://130point.com/sales/?" + urlencode({"search": query, "sort": "date"})

    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    sales = []
    # 130point's results are in a table — exact structure may shift, so we're
    # defensive and bail on anything that doesn't parse cleanly.
    table = soup.find("table")
    if not table:
        return []
    for row in table.find_all("tr")[1:]:  # skip header
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) < 3:
            continue
        price = _parse_price(cells)
        date = _parse_date(cells)
        link = row.find("a")
        if price is None or date is None:
            continue
        sales.append({
            "price": price,
            "date": date,
            "url": link.get("href") if link else None,
        })
        if len(sales) >= 25:
            break
    return sales


def _parse_price(cells: list[str]) -> Optional[float]:
    for c in cells:
        if c.startswith("$"):
            try:
                return float(c.replace("$", "").replace(",", ""))
            except ValueError:
                continue
    return None


def _parse_date(cells: list[str]) -> Optional[str]:
    for c in cells:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(c, fmt).date().isoformat()
            except ValueError:
                continue
    return None
