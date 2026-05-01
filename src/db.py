"""SQLite schema and helpers for the auction scanner."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "auctions.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS auctions (
    item_id           TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    url               TEXT,
    image_url         TEXT,
    seller_feedback   INTEGER,
    seller_pos_pct    REAL,
    current_price     REAL,
    bid_count         INTEGER,
    end_time          TEXT,           -- ISO8601 UTC
    listing_type      TEXT,           -- 'AUCTION' or 'AUCTION_WITH_BIN'
    -- parsed fields
    year              INTEGER,
    product           TEXT,
    player            TEXT,
    parallel_name     TEXT,
    parallel_tier     INTEGER,
    print_run         INTEGER,
    grade             TEXT,
    card_number       TEXT,
    is_first_bowman   INTEGER,
    -- bookkeeping
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    rejected_reason   TEXT
);

CREATE INDEX IF NOT EXISTS idx_auctions_endtime ON auctions(end_time);
CREATE INDEX IF NOT EXISTS idx_auctions_player ON auctions(player);

CREATE TABLE IF NOT EXISTS comps (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    player            TEXT NOT NULL,
    year              INTEGER,
    product           TEXT,
    parallel_name     TEXT,
    grade             TEXT,
    sale_price        REAL NOT NULL,
    sale_date         TEXT NOT NULL,
    source            TEXT,           -- '130point' | 'ebay-sold' | 'manual'
    source_url        TEXT,
    fetched_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comps_lookup
    ON comps (player, year, parallel_name, grade);

CREATE TABLE IF NOT EXISTS scores (
    item_id           TEXT NOT NULL,
    scored_at         TEXT NOT NULL,
    comp_median       REAL,
    comp_count        INTEGER,
    suggested_max_bid REAL,
    score             REAL,           -- higher = better deal
    rarity_weight     REAL,
    grade_weight      REAL,
    shill_risk        TEXT,           -- 'low' | 'medium' | 'high'
    shill_reasons     TEXT,           -- JSON array of strings
    rationale         TEXT,
    PRIMARY KEY (item_id, scored_at),
    FOREIGN KEY (item_id) REFERENCES auctions(item_id)
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_auction(conn: sqlite3.Connection, row: dict) -> None:
    """Insert or update an auction row. Uses item_id as the key."""
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    set_clause = ",".join(f"{c}=excluded.{c}" for c in cols if c != "item_id" and c != "first_seen")
    sql = (
        f"INSERT INTO auctions ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(item_id) DO UPDATE SET {set_clause}"
    )
    conn.execute(sql, [row[c] for c in cols])


def insert_score(conn: sqlite3.Connection, score: dict) -> None:
    cols = list(score.keys())
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO scores ({','.join(cols)}) VALUES ({placeholders})",
        [score[c] for c in cols],
    )


def insert_comp(conn: sqlite3.Connection, comp: dict) -> None:
    cols = list(comp.keys())
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT INTO comps ({','.join(cols)}) VALUES ({placeholders})",
        [comp[c] for c in cols],
    )
