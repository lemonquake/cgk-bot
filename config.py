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

# ── Engagement contest ─────────────────────────────────────────────────────
# Only activity inside these channels (and their threads) is ever counted.
CONTEST_CHANNEL_IDS: set[int] = {
    1490809573194469436,
    1490808945512550461,
    1545143862539067403,
    1490808644185624627,
}
CONTEST_EXCLUDED_ROLE_IDS: set[int] = {
    1542915539872125049,
    1409595982353531092,
    1545098049238597692,
}
CONTEST_REPORT_CHANNEL_ID = _optional_int(
    "CONTEST_REPORT_CHANNEL_ID", "1541562452993511584"
)

# Point weighting
CONTEST_POINTS_MESSAGE = _positive_int("CONTEST_POINTS_MESSAGE", 2)
CONTEST_POINTS_REACTION = _positive_int("CONTEST_POINTS_REACTION", 1)
CONTEST_POINTS_TIKTOK = _positive_int("CONTEST_POINTS_TIKTOK", 10)

# Genuine-message rules. A message only earns points when it clears every one
# of these gates, which is what keeps one-word replies, spam bursts and
# copy-pasted text from farming the leaderboard.
#
# ▸ MIN_WORDS            minimum real words left after links, mentions and
#                        emoji are stripped out ("more than 2 words")
# ▸ SELF_REPEAT_HOURS    the same person repeating the same text inside this
#                        window only scores the first time
# ▸ CROSS_REPEAT_MINUTES identical text copied between different people inside
#                        this window only scores for whoever said it first
# ▸ COOLDOWN_SECONDS     minimum gap between two scoring messages from the
#                        same person (rapid-fire burst guard)
CONTEST_MIN_MESSAGE_WORDS = _positive_int("CONTEST_MIN_MESSAGE_WORDS", 3)
CONTEST_SELF_REPEAT_HOURS = _positive_int("CONTEST_SELF_REPEAT_HOURS", 24)
CONTEST_CROSS_REPEAT_MINUTES = _positive_int("CONTEST_CROSS_REPEAT_MINUTES", 60)
CONTEST_MESSAGE_COOLDOWN_SECONDS = _positive_int(
    "CONTEST_MESSAGE_COOLDOWN_SECONDS", 10
)

# How many past contests the "Past Contests" browser lists at once
CONTEST_HISTORY_LIMIT = _positive_int("CONTEST_HISTORY_LIMIT", 25)

# Community database powering onboarding logs, growth snapshots and live reports
COMMUNITY_DATABASE_PATH = Path(
    os.getenv("COMMUNITY_DATABASE_PATH", "data/community.sqlite3")
)

# Where banner and message pictures are kept once a moderator uploads them.
# They are stored locally on purpose: a Discord image link expires, and a
# saved announcement has to keep its banner long after the link it came from
# stopped working.
BANNER_ASSET_PATH = Path(os.getenv("BANNER_ASSET_PATH", "data/banners"))

# Default onboarding channels. These are only starting values: moderators can
# change them at any time from the Mod Panel (Information Onboarding -> Settings),
# and those saved choices always win over the values below.
WELCOME_CHANNEL_ID = _optional_int("WELCOME_CHANNEL_ID")
ONBOARDING_CHANNEL_ID = _optional_int("ONBOARDING_CHANNEL_ID")
INTRODUCTIONS_CHANNEL_ID = _optional_int("INTRODUCTIONS_CHANNEL_ID")

# Creator onboarding (the TikTok Shop question): where the interactive welcome
# is posted by default, the getting-started channel (#🛍️tiktok-shop-101) that
# learning creators are sent to, and #opportunities-to-earn, linked in the
# message members get once they finish. All can be changed from the Mod Panel
# (Onboarding -> Settings); saved choices win over these values.
CREATOR_WELCOME_CHANNEL_ID = _optional_int("CREATOR_WELCOME_CHANNEL_ID")
CREATOR_GETTING_STARTED_CHANNEL_ID = _optional_int(
    "CREATOR_GETTING_STARTED_CHANNEL_ID", "1557490449160085615"
)
CREATOR_OPPORTUNITIES_CHANNEL_ID = _optional_int(
    "CREATOR_OPPORTUNITIES_CHANNEL_ID", "1557773483243741226"
)

# CGK Onboarding: each new member gets a private "<handle>-onboarding"
# channel in this category, and finishing the questionnaire there grants the
# access role that unlocks the rest of the server. Both can be changed from
# the Mod Panel (CGK Onboarding -> Settings); saved choices win.
CGK_ONBOARDING_CATEGORY_ID = _optional_int(
    "CGK_ONBOARDING_CATEGORY_ID", "1557840609664958599"
)
CGK_ONBOARDING_ROLE_ID = _optional_int("CGK_ONBOARDING_ROLE_ID", "1534216662415573023")

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

# Member questionnaire: fixed brand destination; Slack URL is a private secret.
QUESTIONNAIRE_CHANNEL_ID = 1377025469752410264
SLACK_ONBOARDING_WEBHOOK_URL = os.getenv("SLACK_ONBOARDING_WEBHOOK_URL", "").strip()
