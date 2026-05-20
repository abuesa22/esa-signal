import sqlite3
import json
import logging
from config import DB_PATH
from database.models import TokenSignal

logger = logging.getLogger(__name__)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS signals (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                token_address     TEXT NOT NULL,
                chain             TEXT NOT NULL,
                ticker            TEXT,
                name              TEXT,
                price_usd         REAL,
                market_cap        REAL,
                volume_24h        REAL,
                liquidity_usd     REAL,
                holder_count      INTEGER,
                price_change_1h   REAL,
                price_change_24h  REAL,
                age_hours         REAL,
                gate1_passed      INTEGER DEFAULT 0,
                gate2_passed      INTEGER DEFAULT 0,
                gate3_passed      INTEGER DEFAULT 0,
                gate4_passed      INTEGER DEFAULT 0,
                rugcheck_score    REAL,
                coingecko_listed  INTEGER DEFAULT 0,
                cmc_listed        INTEGER DEFAULT 0,
                ai_score          INTEGER,
                narrative         TEXT,
                conviction        TEXT,
                risks             TEXT,
                entry_zone_low    REAL,
                entry_zone_high   REAL,
                position_size     TEXT,
                urgency           TEXT,
                trending_rank     INTEGER,
                dexscreener_url   TEXT,
                coingecko_url     TEXT,
                cmc_url           TEXT,
                sent_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                outcome           TEXT
            );

            CREATE TABLE IF NOT EXISTS market_briefs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_type  TEXT NOT NULL,
                content     TEXT NOT NULL,
                sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scanned_tokens (
                token_address  TEXT PRIMARY KEY,
                chain          TEXT,
                first_seen     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_scanned   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS graduation_watchlist (
                token_address  TEXT PRIMARY KEY,
                chain          TEXT NOT NULL,
                ticker         TEXT,
                name           TEXT,
                first_seen     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_checked   TIMESTAMP,
                volume_peak    REAL DEFAULT 0,
                graduated      INTEGER DEFAULT 0
            );
        """)
    logger.info("Database ready at %s", DB_PATH)


def save_signal(sig: TokenSignal) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO signals (
                token_address, chain, ticker, name, price_usd, market_cap, volume_24h,
                liquidity_usd, holder_count, price_change_1h, price_change_24h, age_hours,
                gate1_passed, gate2_passed, gate3_passed, gate4_passed, rugcheck_score,
                coingecko_listed, cmc_listed, ai_score, narrative, conviction, risks,
                entry_zone_low, entry_zone_high, position_size, urgency, trending_rank,
                dexscreener_url, coingecko_url, cmc_url
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sig.token_address, sig.chain, sig.ticker, sig.name,
                sig.price_usd, sig.market_cap, sig.volume_24h, sig.liquidity_usd,
                sig.holder_count, sig.price_change_1h, sig.price_change_24h, sig.age_hours,
                int(sig.gate1_passed), int(sig.gate2_passed),
                int(sig.gate3_passed), int(sig.gate4_passed),
                sig.rugcheck_score, int(sig.coingecko_listed), int(sig.cmc_listed),
                sig.ai_score, sig.narrative, sig.conviction, json.dumps(sig.risks),
                sig.entry_zone_low, sig.entry_zone_high, sig.position_size, sig.urgency,
                sig.trending_rank, sig.dexscreener_url, sig.coingecko_url, sig.cmc_url,
            ),
        )
        return cur.lastrowid


def is_already_alerted(token_address: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM signals WHERE token_address = ?", (token_address,)
        ).fetchone()
        return row is not None


def mark_scanned(token_address: str, chain: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO scanned_tokens (token_address, chain, last_scanned)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (token_address, chain),
        )


def was_scanned_recently(token_address: str, within_minutes: int = 60) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT last_scanned FROM scanned_tokens
               WHERE token_address = ?
               AND last_scanned > datetime('now', ?)""",
            (token_address, f"-{within_minutes} minutes"),
        ).fetchone()
        return row is not None


def update_outcome(signal_id: int, outcome: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE signals SET outcome = ? WHERE id = ?", (outcome, signal_id)
        )


def get_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        outcomes = conn.execute(
            "SELECT outcome, COUNT(*) FROM signals WHERE outcome IS NOT NULL GROUP BY outcome"
        ).fetchall()
        outcome_map = {r[0]: r[1] for r in outcomes}
        wins = sum(v for k, v in outcome_map.items() if k in ("2x", "5x", "10x"))
        losses = outcome_map.get("LOSS", 0)
        evaluated = wins + losses
        win_rate = (wins / evaluated * 100) if evaluated > 0 else 0.0
        avg_score = conn.execute("SELECT AVG(ai_score) FROM signals").fetchone()[0] or 0
        return {
            "total_signals": total,
            "evaluated": evaluated,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "avg_ai_score": round(avg_score, 1),
            "outcomes": outcome_map,
        }


def get_recent_signals(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY sent_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_top_signals(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM signals
               WHERE outcome IN ('10x','5x','2x')
               ORDER BY CASE outcome
                   WHEN '10x' THEN 3
                   WHEN '5x'  THEN 2
                   WHEN '2x'  THEN 1
               END DESC, ai_score DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_to_graduation_watchlist(token_address: str, chain: str, ticker: str, name: str, volume: float):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO graduation_watchlist (token_address, chain, ticker, name, volume_peak)
               VALUES (?, ?, ?, ?, ?)""",
            (token_address, chain, ticker, name, volume),
        )
        conn.execute(
            """UPDATE graduation_watchlist
               SET volume_peak = MAX(volume_peak, ?), last_checked = CURRENT_TIMESTAMP
               WHERE token_address = ?""",
            (volume, token_address),
        )


def get_graduation_watchlist() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM graduation_watchlist
               WHERE graduated = 0
               ORDER BY volume_peak DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def mark_graduated(token_address: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE graduation_watchlist SET graduated = 1, last_checked = CURRENT_TIMESTAMP WHERE token_address = ?",
            (token_address,),
        )


def save_market_brief(brief_type: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO market_briefs (brief_type, content) VALUES (?, ?)",
            (brief_type, content),
        )
