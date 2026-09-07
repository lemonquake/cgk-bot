"""
Configuration settings for the CGK Linens Discord Bot.
Created by Aljay Leodones for CGK Linens.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def _optional_int(name: str, default: str = "") -> int | None:
    """Reads an optional numeric environment variable (blank/invalid -> None)."""
    raw = (os.getenv(name, default) or "").strip()
    return int(raw) if raw.isdigit() else None


def _positive_int(name: str, default: int) -> int:
    raw = (os.getenv(name, "") or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else default


def _flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


# Discord Bot Token
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Optional Guild ID for testing/instant slash command updates
GUILD_ID = _optional_int("GUILD_ID")

# Engagement reporting
REPORT_CHANNEL_ID = _optional_int("REPORT_CHANNEL_ID", "1541562452993511584")
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "Asia/Manila")
ACTIVITY_DATABASE_PATH = Path(
    os.getenv("ACTIVITY_DATABASE_PATH", "data/engagement.sqlite3")
)

# Engagement contest settings
CONTEST_CHANNEL_IDS: set[int] = {
    1490809573194469436,
    1490808945512550461,
    1534244419752956024,
    1539653929313374290,
    1534246299413647442,
    1534268959660970244,
}
CONTEST_EXCLUDED_ROLE_IDS: set[int] = {
    1542915539872125049,
    1409595982353531092,
    1545098049238597692,
}
CONTEST_REPORT_CHANNEL_ID = _optional_int(
    "CONTEST_REPORT_CHANNEL_ID", "1541562452993511584"
)
CONTEST_POINTS_MESSAGE = _positive_int("CONTEST_POINTS_MESSAGE", 3)
CONTEST_POINTS_REACTION = _positive_int("CONTEST_POINTS_REACTION", 1)
CONTEST_POINTS_TIKTOK = _positive_int("CONTEST_POINTS_TIKTOK", 5)

# Community database powering onboarding logs, growth snapshots and live reports
COMMUNITY_DATABASE_PATH = Path(
    os.getenv("COMMUNITY_DATABASE_PATH", "data/community.sqlite3")
)

# Default onboarding channels. These are only starting values: moderators can
# change them at any time from the Mod Panel (Onboarding -> Channel Setup),
# and those saved choices always win over the values below.
WELCOME_CHANNEL_ID = _optional_int("WELCOME_CHANNEL_ID")
ONBOARDING_CHANNEL_ID = _optional_int("ONBOARDING_CHANNEL_ID")
INTRODUCTIONS_CHANNEL_ID = _optional_int("INTRODUCTIONS_CHANNEL_ID")

# How far back the onboarding scanner looks for members that were never welcomed
ONBOARDING_LOOKBACK_DAYS = _positive_int("ONBOARDING_LOOKBACK_DAYS", 30)

# How often deployed live community reports refresh themselves (hours)
REPORT_REFRESH_HOURS = _positive_int("REPORT_REFRESH_HOURS", 3)

# Presence intent unlocks the "Online now" metric in community reports. It must
# also be enabled in the Discord Developer Portal; the bot automatically falls
# back to running without it when the portal switch is off.
ENABLE_PRESENCE_INTENT = _flag("ENABLE_PRESENCE_INTENT", True)

# Brand theme & aesthetics
BRAND_NAME = "CGK Linens"
BOT_NAME = "CGK Linens Bot"
BRAND_COLOR = 0x1B365D  # Elegant Navy Blue
EMBED_FOOTER_TEXT = "CGK Linens Management Bot • Created by Aljay Leodones"

# Unified embed palette (see utils/embed_builder.py)
COLOR_BRAND = BRAND_COLOR  # Navy — default brand surface
COLOR_ACCENT = 0xC8A96A  # Warm champagne gold accent
COLOR_SUCCESS = 0x2ECC71  # Emerald Green
COLOR_ERROR = 0xE74C3C  # Crimson Red
COLOR_WARNING = 0xF1C40F  # Amber Yellow
COLOR_INFO = 0x3498DB  # Sapphire Blue
