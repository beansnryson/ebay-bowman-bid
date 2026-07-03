"""eBay Browse API client.

Two modes:
  - LIVE: real Browse API, requires EBAY_APP_ID + EBAY_CERT_ID env vars
  - MOCK: returns canned sample listings for offline testing

Daily flow searches for active auctions in the Sports Trading Cards category
(261328) matching Bowman 1st auto queries, ending in the next 24h.

Note on bid history: eBay Browse API does NOT return bid history. To pull
that we'd need the older Trading API (XML-based, separate auth). For now
shill detection works off seller stats + bid count vs price velocity. The
project leaves a hook so we can layer in the Trading API later.
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SPORTS_CARDS_CATEGORY_ID = "261328"

# Per-player query templates — each player gets searched with these suffixes.
# Targeted queries return ~5-50 results each instead of thousands.
PLAYER_QUERY_SUFFIXES = [
    "Bowman Chrome Auto",
    "Bowman Draft Auto",
]

MAX_PAGES_PER_QUERY = 3   # cap pagination — 3 pages × 100 = 300 results / player / query


@dataclass
class EbayListing:
    item_id: str
    title: str
    url: str
    image_url: Optional[str]
    seller_username: Optional[str]
    seller_feedback: Optional[int]
    seller_pos_pct: Optional[float]
    current_price: Optional[float]
    bid_count: Optional[int]
    end_time: Optional[str]
    listing_type: Optional[str]


class EbayClient:
    def __init__(self, app_id: str | None = None, cert_id: str | None = None,
                 epn_campaign: str | None = None):
        self.app_id = app_id or os.getenv("EBAY_APP_ID")
        self.cert_id = cert_id or os.getenv("EBAY_CERT_ID")
        self.epn_campaign = epn_campaign or os.getenv("EBAY_EPN_CAMPAIGN_ID")
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        if not self.app_id or not self.cert_id:
            raise RuntimeError(
                "EBAY_APP_ID / EBAY_CERT_ID not set — copy .env.example to .env "
                "and add credentials from developer.ebay.com."
            )
        resp = requests.post(
            EBAY_OAUTH_URL,
            auth=(self.app_id, self.cert_id),
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data["expires_in"]
        return self._token

    def _headers(self) -> dict:
        h = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }
        if self.epn_campaign:
            h["X-EBAY-C-ENDUSERCTX"] = f"affiliateCampaignId={self.epn_campaign}"
        return h

    def search_ending_soon(self, hours_ahead: int = 24, players: list[str] | None = None) -> Iterator[EbayListing]:
        """Yield auctions ending in the next N hours.

        If `players` is provided, runs targeted per-player searches —
        much faster and more precise than broad queries.
        """
        # Open-ended range only — Browse API rejects [start..end] for
        # itemEndDate (errorId 12002) and silently drops the filter. Active
        # listings can't end in the past, so [..end_max] gives the same window.
        end_max = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
        end_filter = f"itemEndDate:[..{end_max.strftime('%Y-%m-%dT%H:%M:%SZ')}]"

        seen: set[str] = set()
        if not players:
            print("  WARNING: no player list — falling back to broad search", flush=True)
            players = [""]
        for i, player in enumerate(players, 1):
            for suffix in PLAYER_QUERY_SUFFIXES:
                query = f'"{player}" {suffix}'.strip() if player else suffix
                print(f"  [{i}/{len(players)}] Query: {query!r}", flush=True)
                for listing in self._search(query, end_filter):
                    if listing.item_id in seen:
                        continue
                    seen.add(listing.item_id)
                    yield listing

    def _search(self, query: str, end_filter: str) -> Iterator[EbayListing]:
        offset = 0
        limit = 100
        pages = 0
        while pages < MAX_PAGES_PER_QUERY:
            params = {
                "q": query,
                "category_ids": SPORTS_CARDS_CATEGORY_ID,
                # AUCTION covers auction-with-BIN too; an invalid value here
                # (e.g. AUCTION_WITH_BIN) makes eBay silently ignore the whole
                # filter string — we learned this the hard way.
                "filter": f"buyingOptions:{{AUCTION}},{end_filter}",
                "limit": limit,
                "offset": offset,
            }
            resp = requests.get(EBAY_BROWSE_URL, params=params, headers=self._headers(), timeout=60)
            resp.raise_for_status()
            data = resp.json()
            for w in data.get("warnings", []) or []:
                print(f"  API WARNING {w.get('errorId')}: {w.get('message')}", flush=True)
            items = data.get("itemSummaries", []) or []
            for item in items:
                yield _to_listing(item)
            total = data.get("total", 0)
            offset += limit
            pages += 1
            if offset >= total or not items:
                break


def _to_listing(item: dict) -> EbayListing:
    seller = item.get("seller", {}) or {}
    price = (item.get("currentBidPrice") or item.get("price") or {}).get("value")
    return EbayListing(
        item_id=item.get("itemId", ""),
        title=item.get("title", ""),
        url=item.get("itemWebUrl") or item.get("itemHref") or "",
        image_url=(item.get("image") or {}).get("imageUrl"),
        seller_username=seller.get("username"),
        seller_feedback=seller.get("feedbackScore"),
        seller_pos_pct=_to_float(seller.get("feedbackPercentage")),
        current_price=_to_float(price),
        bid_count=item.get("bidCount"),
        end_time=item.get("itemEndDate"),
        listing_type=",".join(item.get("buyingOptions", []) or []),
    )


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --- Mock client for offline development ---

MOCK_LISTINGS = [
    EbayListing(
        item_id="MOCK-001",
        title="2023 Bowman Chrome Junior Caminero #BCP-100 Prospect Auto Refractor PSA 10",
        url="https://www.ebay.com/itm/MOCK-001",
        image_url=None,
        seller_username="topshelfcards",
        seller_feedback=4823,
        seller_pos_pct=99.7,
        current_price=412.0,
        bid_count=14,
        end_time=(datetime.now(timezone.utc) + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        listing_type="AUCTION",
    ),
    EbayListing(
        item_id="MOCK-002",
        title="JUNIOR CAMINERO 2023 Bowman Chrome PROSPECT AUTO RC GOLD /50 BGS 9.5",
        url="https://www.ebay.com/itm/MOCK-002",
        image_url=None,
        seller_username="newbie_seller_22",
        seller_feedback=4,
        seller_pos_pct=100.0,
        current_price=625.0,
        bid_count=23,
        end_time=(datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        listing_type="AUCTION",
    ),
    EbayListing(
        item_id="MOCK-003",
        title="Roki Sasaki 2024 Bowman Chrome Sapphire Edition 1st Auto SUPERFRACTOR 1/1",
        url="https://www.ebay.com/itm/MOCK-003",
        image_url=None,
        seller_username="elitesportscards",
        seller_feedback=12480,
        seller_pos_pct=99.9,
        current_price=18500.0,
        bid_count=31,
        end_time=(datetime.now(timezone.utc) + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        listing_type="AUCTION",
    ),
    EbayListing(
        item_id="MOCK-004",
        title="2025 Bowman Draft Konnor Griffin BD-150 Chrome Prospect Auto Sky Blue /499",
        url="https://www.ebay.com/itm/MOCK-004",
        image_url=None,
        seller_username="cardvault_pro",
        seller_feedback=987,
        seller_pos_pct=99.5,
        current_price=42.0,
        bid_count=8,
        end_time=(datetime.now(timezone.utc) + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        listing_type="AUCTION",
    ),
    EbayListing(
        item_id="MOCK-005",
        title="2024 Bowman Chrome Hobby Box Sealed",
        url="https://www.ebay.com/itm/MOCK-005",
        image_url=None,
        seller_username="bigboxbreaker",
        seller_feedback=200,
        seller_pos_pct=98.0,
        current_price=320.0,
        bid_count=2,
        end_time=(datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        listing_type="AUCTION",
    ),
]


class MockEbayClient:
    def search_ending_soon(self, hours_ahead: int = 24) -> Iterator[EbayListing]:
        yield from MOCK_LISTINGS
