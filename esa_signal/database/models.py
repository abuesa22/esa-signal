from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TokenSignal:
    token_address: str
    chain: str
    ticker: str
    name: str
    price_usd: float
    market_cap: float
    volume_24h: float
    liquidity_usd: float
    holder_count: int
    price_change_1h: float
    price_change_24h: float
    age_hours: float

    # Gate results
    gate1_passed: bool = False
    gate2_passed: bool = False
    gate3_passed: bool = False
    gate4_passed: bool = False

    # Safety data
    rugcheck_score: float = 0.0
    rugcheck_risks: list = field(default_factory=list)
    has_mint_authority: bool = False
    has_freeze_authority: bool = False
    lp_locked: bool = False

    # Launch classification (not persisted to DB)
    launch_tag: str = ""  # "JUST LAUNCHED" / "NEW TODAY" / ""

    # Legitimacy
    coingecko_listed: bool = False
    cmc_listed: bool = False

    # AI output
    ai_score: int = 0
    narrative: str = ""
    conviction: str = "LOW"   # LOW / MEDIUM / HIGH
    risks: list = field(default_factory=list)

    # Trade setup
    entry_zone_low: float = 0.0
    entry_zone_high: float = 0.0
    position_size: str = "SMALL"   # SMALL / MEDIUM / LARGE
    urgency: str = "LOW"           # LOW / MEDIUM / HIGH / APE NOW

    # Optional extras
    trending_rank: Optional[int] = None
    dexscreener_url: str = ""
    coingecko_url: str = ""
    cmc_url: str = ""

    # DB fields
    id: Optional[int] = None
    sent_at: Optional[datetime] = None
    outcome: Optional[str] = None  # 2x / 5x / 10x / LOSS / HOLD


@dataclass
class MarketBrief:
    brief_type: str   # morning / midday / evening
    content: str
    sent_at: Optional[datetime] = None
    id: Optional[int] = None
