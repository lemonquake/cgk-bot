"""
Member onboarding engine: scan, welcome post, warm DM and onboarding log.
Created by Aljay Leodones for CGK Linens.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging

import discord
from discord.ext import commands

from config import (
    BRAND_NAME,
    COMMUNITY_DATABASE_PATH,
    INTRODUCTIONS_CHANNEL_ID,
    ONBOARDING_CHANNEL_ID,
    ONBOARDING_LOOKBACK_DAYS,
    WELCOME_CHANNEL_ID,
)
from core.database import get_database
from core.embed_script import resolve_text
from utils import embed_builder

logger = logging.getLogger("cgk_bot.onboarding")

# Setting keys stored per guild in `guild_settings`
CHANNEL_SETTINGS = {
    "welcome": "welcome_channel_id",
    "onboarding": "onboarding_channel_id",
    "introductions": "introductions_channel_id",
}
CHANNEL_LABELS = {
    "welcome": "Welcome / announcements",
    "onboarding": "Start here (onboarding)",
    "introductions": "Introductions",
}
ENV_CHANNEL_DEFAULTS = {
    "welcome": WELCOME_CHANNEL_ID,
    "onboarding": ONBOARDING_CHANNEL_ID,
    "introductions": INTRODUCTIONS_CHANNEL_ID,
}

# Default, fully editable welcome post. Placeholders are hydrated on send.
DEFAULT_MESSAGE = (
    "\U0001F44B **Please give a warm welcome to our newest members!**\n\n"
    "Welcome to the **CGK Linens** community — we're thrilled to have you here! \U0001F389\n\n"
    "**◈  Start here →** {onboarding_channel}\n"
    "Everything you need to get comfortable lives there — product guides, care "
    "tips, ordering help and all the essentials.\n\n"
    "**◈  Say hello →** {introductions_channel}\n"
    "Pop in to introduce yourself! Tell us a little about you and what brought "
    "you to CGK Linens so the community can connect with you. \U0001F90D"
)

MAX_MESSAGE_LENGTH = 1900


@dataclass(slots=True)
class DayGroup:
    """One selectable join-day bucket shown in the onboarding day picker."""

    key: str
    label: str
    description: str
    members: list[discord.Member] = field(default_factory=list)


@dataclass(slots=True)
class DeliveryResult:
    posted_channel: discord.abc.GuildChannel | None = None
    dm_success: int = 0
    dm_failed: int = 0
    failed_names: list[str] = field(default_factory=list)
    marked: int = 0


def _bucket_for(days_ago: int) -> tuple[str, str, str]:
    """Maps a join age in days to a (key, label, description) bucket."""
    if days_ago <= 0:
        return "d0", "Joined today", "Members who joined in the last 24 hours"
    if days_ago == 1:
        return "d1", "Joined yesterday", "Members who joined 1 day ago"
    if days_ago <= 6:
        return (
            f"d{days_ago}",
            f"Joined {days_ago} days ago",
            f"Members who joined {days_ago} days ago",
        )
    if days_ago <= 13:
        return "w1", "Joined 1 week ago", "Members who joined 7-13 days ago"
    if days_ago <= 20:
        return "w2", "Joined 2 weeks ago", "Members who joined 14-20 days ago"
    return "w3", "Joined 3+ weeks ago", "Members who joined 21+ days ago"


def _chunk_mentions(
    mentions: list[str], first_budget: int, later_budget: int
) -> list[str]:
    """Groups mentions into space-separated blocks that fit a message."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    budget = first_budget
    for mention in mentions:
        if current and length + len(mention) + 1 > budget:
            chunks.append(" ".join(current))
            current, length = [], 0
            budget = later_budget
        current.append(mention)
        length += len(mention) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks or [""]


def _bucket_order(key: str) -> tuple[int, int]:
    if key.startswith("d"):
        return (0, int(key[1:]))
    return (1, int(key[1:]))


class OnboardingCog(commands.Cog, name="OnboardingCog"):
    """Scans for un-welcomed members and delivers branded onboarding messages."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = get_database(COMMUNITY_DATABASE_PATH)

    async def cog_load(self) -> None:
        await self.db.initialize()
        logger.info("Onboarding ready (lookback: %s days)", ONBOARDING_LOOKBACK_DAYS)

    # -- channel configuration ---------------------------------
    async def channel_ids(self, guild_id: int) -> dict[str, int | None]:
        """Saved channel choices, falling back to the .env defaults."""
        stored = await self.db.get_settings(
            guild_id, list(CHANNEL_SETTINGS.values())
        )
        resolved: dict[str, int | None] = {}
        for key, setting in CHANNEL_SETTINGS.items():
            value = stored.get(setting)
            if value and value.isdigit():
                resolved[key] = int(value)
            else:
                resolved[key] = ENV_CHANNEL_DEFAULTS[key]
        return resolved

    async def set_channel(self, guild_id: int, key: str, channel_id: int | None) -> None:
        await self.db.set_setting(
            guild_id, CHANNEL_SETTINGS[key], str(channel_id) if channel_id else None
        )

    # -- onboarding log ----------------------------------------
    async def onboarded_ids(self, guild_id: int) -> set[int]:
        rows = await self.db.fetchall(
            "SELECT user_id FROM onboarded_members WHERE guild_id = ?", (guild_id,)
        )
        return {row["user_id"] for row in rows}

    async def mark_onboarded(
        self,
        guild_id: int,
        member_ids: list[int],
        *,
        moderator_id: int | None = None,
        method: str = "panel",
    ) -> int:
        if not member_ids:
            return 0
        await self.db.executemany(
            """
            INSERT INTO onboarded_members (user_id, guild_id, onboarded_by, method)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                onboarded_at = datetime('now'),
                onboarded_by = excluded.onboarded_by,
                method = excluded.method
            """,
            [(member_id, guild_id, moderator_id, method) for member_id in member_ids],
        )
        return len(member_ids)

    async def clear_onboarded(self, guild_id: int) -> int:
        """Clears the log so every recent member becomes selectable again."""
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM onboarded_members WHERE guild_id = ?",
            (guild_id,),
        )
        await self.db.execute(
            "DELETE FROM onboarded_members WHERE guild_id = ?", (guild_id,)
        )
        return row["total"] if row else 0

    async def onboarding_stats(self, guild: discord.Guild) -> dict[str, int]:
        total_row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM onboarded_members WHERE guild_id = ?",
            (guild.id,),
        )
        recent_row = await self.db.fetchone(
            """
            SELECT COUNT(*) AS recent FROM onboarded_members
            WHERE guild_id = ? AND onboarded_at >= datetime('now', '-7 days')
            """,
            (guild.id,),
        )
        pending = await self.pending_members(guild)
        return {
            "total": total_row["total"] if total_row else 0,
            "last_7_days": recent_row["recent"] if recent_row else 0,
            "pending": len(pending),
        }

    # -- scanning ----------------------------------------------
    async def pending_members(self, guild: discord.Guild) -> list[discord.Member]:
        """Non-bot members who joined recently and were never welcomed."""
        already = await self.onboarded_ids(guild.id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=ONBOARDING_LOOKBACK_DAYS)
        pending = [
            member
            for member in guild.members
            if not member.bot
            and member.joined_at is not None
            and member.joined_at.astimezone(timezone.utc) >= cutoff
            and member.id not in already
        ]
        pending.sort(key=lambda member: member.joined_at, reverse=True)
        return pending

    def group_by_day(self, members: list[discord.Member]) -> list[DayGroup]:
        """Buckets pending members by how long ago they joined."""
        now = datetime.now(timezone.utc)
        groups: dict[str, DayGroup] = {}
        for member in members:
            days_ago = max((now - member.joined_at.astimezone(timezone.utc)).days, 0)
            key, label, description = _bucket_for(days_ago)
            group = groups.get(key)
            if group is None:
                group = DayGroup(key=key, label=label, description=description)
                groups[key] = group
            group.members.append(member)

        return [groups[key] for key in sorted(groups, key=_bucket_order)]

    # -- delivery ----------------------------------------------
    def build_welcome_dm(
        self, member: discord.Member, channels: dict[str, int | None]
    ) -> discord.Embed:
        """Warm DM embed using deep-links so the channels open from a DM."""
        guild = member.guild
        onboarding_link = embed_builder.channel_reference(
            guild.id, channels.get("onboarding"), "onboarding"
        )
        intros_link = embed_builder.channel_reference(
            guild.id, channels.get("introductions"), "introductions"
        )

        embed = embed_builder.base_embed(
            title=f"\U0001F44B  Welcome to {BRAND_NAME}!",
            description=(
                f"Hi {member.display_name}, we're so glad you're here! \U0001F389\n\n"
                f"You've just joined the **{guild.name}** community, and we want to "
                "make sure you have the smoothest possible start.\n\n"
                f"{embed_builder.section('Start here')} → {onboarding_link}\n"
                "That's your one-stop hub — product guides, care tips and answers "
                "to the questions we hear most often all live there.\n\n"
                f"{embed_builder.section('Introduce yourself')} → {intros_link}\n"
                "Don't be shy — say hello, tell us a bit about yourself and what "
                "brought you to CGK Linens.\n\n"
                f"{embed_builder.SEPARATOR}\n"
                "Our team is always just a message away. Welcome aboard! \U0001F90D"
            ),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        return embed

    async def dm_welcome(
        self, members: list[discord.Member], channels: dict[str, int | None]
    ) -> tuple[int, int, list[str]]:
        """Sends the warm DM to each member, paced for Discord's rate limits."""
        success, failed, failed_names = 0, 0, []
        for member in members:
            try:
                await member.send(embed=self.build_welcome_dm(member, channels))
                success += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
                if len(failed_names) < 15:
                    failed_names.append(member.display_name)
            await asyncio.sleep(1)  # Rate limit protection
        return success, failed, failed_names

    async def post_welcome(
        self,
        channel: discord.TextChannel | discord.Thread,
        members: list[discord.Member],
        message: str,
        channels: dict[str, int | None],
    ) -> discord.Message:
        """Publishes the welcome post, tagging every selected member."""
        body = resolve_text(message, guild=channel.guild, channels=channels) or DEFAULT_MESSAGE
        allowed = discord.AllowedMentions(users=True, roles=False, everyone=False)
        mentions = [member.mention for member in members]

        # Tag as many members as will fit alongside the message itself, then
        # spill the rest into follow-up messages so nothing exceeds Discord's
        # 2,000 character limit.
        first_budget = MAX_MESSAGE_LENGTH - len(body) - 2
        overflow_budget = MAX_MESSAGE_LENGTH - 40
        if first_budget >= 60:
            chunks = _chunk_mentions(mentions, first_budget, overflow_budget)
            primary = await channel.send(
                content=f"{chunks[0]}\n\n{body}".strip(), allowed_mentions=allowed
            )
            overflow = chunks[1:]
        else:
            primary = await channel.send(
                content=body[:MAX_MESSAGE_LENGTH], allowed_mentions=allowed
            )
            overflow = _chunk_mentions(mentions, overflow_budget, overflow_budget)

        for extra in overflow:
            await channel.send(
                content=f"…and also welcoming: {extra}", allowed_mentions=allowed
            )
        return primary

    async def deliver(
        self,
        *,
        guild: discord.Guild,
        members: list[discord.Member],
        message: str,
        moderator: discord.Member | discord.User,
        channel: discord.TextChannel | discord.Thread | None,
        send_dm: bool,
    ) -> DeliveryResult:
        """Runs the full delivery chain: public post, warm DMs, onboarding log."""
        channels = await self.channel_ids(guild.id)
        result = DeliveryResult()

        if channel is not None:
            await self.post_welcome(channel, members, message, channels)
            result.posted_channel = channel

        if send_dm:
            success, failed, names = await self.dm_welcome(members, channels)
            result.dm_success = success
            result.dm_failed = failed
            result.failed_names = names

        result.marked = await self.mark_onboarded(
            guild.id,
            [member.id for member in members],
            moderator_id=moderator.id,
            method="panel" if channel else "dm-only",
        )
        logger.info(
            "Onboarded %s member(s) in guild %s (post: %s, DMs: %s ok / %s failed)",
            result.marked,
            guild.id,
            bool(channel),
            result.dm_success,
            result.dm_failed,
        )
        return result


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OnboardingCog(bot))
