# ebay-bowman-bid

Daily scanner for Bowman 1st autographed baseball card auctions on eBay.
Pulls auctions ending in the next 24 hours, compares the current bid against
historical sale comps, and produces a top-20 watchlist with suggested max
bids and shill-bidding warnings.

**Scope:** Bowman Chrome, Bowman Draft, and Bowman flagship 1st auto only —
no Bowman Sterling, Best, Inception, Platinum, or Heritage.

## Setup

```bash
# 1. install deps
pip install -r requirements.txt

# 2. add eBay credentials (after developer.ebay.com approval)
cp .env.example .env
#   → fill in EBAY_APP_ID and EBAY_CERT_ID

# 3. test with mock data (no creds needed)
python -m src.scan --mock

# 4. run the live scan
python -m src.scan
```

## Layout

```
src/
  parallel_tiers.py   — rarity tier map (Superfractor/Gold/Refractor/etc)
  title_parser.py     — extract player/year/parallel/grade from listing titles
  ebay_client.py      — Browse API client + MockEbayClient
  comps.py            — 130point.com sale lookup + cache
  shill_detector.py   — bid-pattern + seller heuristics
  scoring.py          — comp delta × rarity × grade × shill factor
  report.py           — markdown daily report
  scan.py             — main entrypoint
  db.py               — SQLite schema (auctions, comps, scores)
data/
  checklist.csv       — players to track (player_name column required)
  auctions.db         — local SQLite (gitignored)
reports/
  daily_YYYY-MM-DD.md
tests/
  test_title_parser.py
```

## Scoring

```
score = ((comp_median - current_price) / comp_median)
        × rarity_weight × grade_weight × shill_factor
```

Higher score = better deal. Negative score = currently above comp median.

**Rarity weight** (from `parallel_tiers.py`):
- Tier 1 (1/1, Red /5, Printing Plates): 2.5–3.0
- Tier 2 (Orange /25, Gold /50, Atomic /99): 1.7–2.0
- Tier 3 (Blue /150, Green /99, Purple /250): 1.3–1.5
- Tier 4 (Refractor, Sky Blue, Base): 0.9–1.1

**Grade weight:** PSA 10 = 1.5, PSA 9 = 1.0, Raw = 0.7.

**Suggested max bid:** `comp_median × (0.85 + grade_bonus) × rarity_floor` —
targets 15% under median for raw cards, with a small premium for top grades
and rare parallels.

## Shill detection

eBay anonymizes bidder IDs (`b***r`), so we can't conclusively prove shill
bidding. We flag risk based on:

- Low-feedback seller (<25)
- Sub-98% positive feedback
- High bid count on low-feedback seller (>15 bids, <50 feedback)
- Current price already >25% above comp median with active bidding

Risk levels: 🟢 low / 🟡 medium / 🔴 high — discount the score by 0% / 15% / 50%.

## Daily run

```bash
./daily_run.sh
```

Outputs to `reports/daily_YYYY-MM-DD.md` and appends to `scan.log`.

## Tests

```bash
python -m pytest tests/
```
