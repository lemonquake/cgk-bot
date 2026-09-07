"""
Engagement Contest tracking and leaderboard generation for CGK Linens.
Created by Aljay Leodones for CGK Linens.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import sqlite3
from typing import Iterable

import discord
from discord.ext import commands

from config import (
    ACTIVITY_DATABASE_PATH,
    COLOR_ACCENT,
    CONTEST_CHANNEL_IDS,
    CONTEST_EXCLUDED_ROLE_IDS,
    CONTEST_POINTS_MESSAGE,
    CONTEST_POINTS_REACTION,
    CONTEST_POINTS_TIKTOK,
    CONTEST_REPORT_CHANNEL_ID,
    EMBED_FOOTER_TEXT,
)
from utils import embed_builder

logger = logging.getLogger("cgk_bot.engagement_contest")

# Regex to detect TikTok video URLs
TIKTOK_URL_PATTERN = re.compile(
    r"https?://(?:www\.|vm\.|vt\.|m\.)?tiktok\.com/\S+", re.IGNORECASE
)


@dataclass(slots=True)
class ContestMemberActivity:
    user_id: int
    display_name: str
    messages: int = 0
    reactions: int = 0
    tiktoks: int = 0
    total_points: int = 0


@dataclass(slots=True)
class ContestEvent:
    guild_id: int
    user_id: int
    user_name: str
    channel_id: int
    event_type: str  # 'message', 'reaction', 'tiktok'
    occurred_at: datetime
    event_key: str
    points: int


@dataclass(slots=True)
class ContestScanStats:
    channels_scanned: int = 0
    messages_scanned: int = 0
    reactions_scanned: int = 0
    tiktoks_detected: int = 0
    locations_skipped: int = 0


def contains_tiktok_link(
    content: str | None, embeds: list[discord.Embed] | None = None
) -> bool:
    """True if message content or embeds contain a TikTok video link."""
    if content and TIKTOK_URL_PATTERN.search(content):
        return True
    if embeds:
        for embed in embeds:
            if embed.url and TIKTOK_URL_PATTERN.search(embed.url):
                return True
            if embed.description and TIKTOK_URL_PATTERN.search(embed.description):
                return True
    return False


def is_contest_channel(channel: discord.abc.GuildChannel | discord.Thread | None) -> bool:
    """True if the channel is one of the designated contest channels or a thread inside one."""
    if channel is None:
        return False
    if channel.id in CONTEST_CHANNEL_IDS:
        return True
    parent_id = getattr(channel, "parent_id", None)
    return bool(parent_id and parent_id in CONTEST_CHANNEL_IDS)


def is_excluded_member(member: discord.Member | discord.User | None) -> bool:
    """True if the user is a bot or holds any excluded moderator/bot roles."""
    if member is None or getattr(member, "bot", False):
        return True
    roles = getattr(member, "roles", None)
    if roles:
        if any(role.id in CONTEST_EXCLUDED_ROLE_IDS for role in roles):
            return True
    return False


class ContestStore:
    """SQLite event store dedicated to the Engagement Contest."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self._lock = asyncio.Lock()
        self._connection: sqlite3.Connection | None = None

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path, timeout=30, check_same_thread=False
        )
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Contest database is not initialized.")
        return self._connection

    async def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        def create_schema() -> None:
            self._connection = self._open_connection()
            with self._connection as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS contest_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        user_name TEXT NOT NULL,
                        channel_id INTEGER NOT NULL,
                        event_type TEXT NOT NULL CHECK (
                            event_type IN ('message', 'reaction', 'tiktok')
                        ),
                        occurred_at TEXT NOT NULL,
                        event_key TEXT NOT NULL,
                        points INTEGER NOT NULL,
                        UNIQUE (guild_id, event_key)
                    );

                    CREATE INDEX IF NOT EXISTS contest_events_range_idx
                    ON contest_events (guild_id, occurred_at, user_id);
                    """
                )

        async with self._lock:
            await asyncio.to_thread(create_schema)

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await asyncio.to_thread(self._connection.close)
                self._connection = None

    async def record_events(self, events: Iterable[ContestEvent]) -> int:
        rows = [
            (
                event.guild_id,
                event.user_id,
                event.user_name,
                event.channel_id,
                event.event_type,
                event.occurred_at.astimezone(timezone.utc).isoformat(),
                event.event_key,
                event.points,
            )
            for event in events
        ]
        if not rows:
            return 0

        def insert() -> int:
            with self._require_connection() as connection:
                changes_before = connection.total_changes
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO contest_events (
                        guild_id, user_id, user_name, channel_id,
                        event_type, occurred_at, event_key, points
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                return connection.total_changes - changes_before

        async with self._lock:
            return await asyncio.to_thread(insert)

    async def aggregate(
        self, guild_id: int, start: datetime, end: datetime
    ) -> list[ContestMemberActivity]:
        def select() -> list[ContestMemberActivity]:
            rows = self._require_connection().execute(
                """
                SELECT
                    user_id,
                    MAX(user_name),
                    SUM(CASE WHEN event_type = 'message' THEN 1 ELSE 0 END) AS msg_count,
                    SUM(CASE WHEN event_type = 'reaction' THEN 1 ELSE 0 END) AS react_count,
                    SUM(CASE WHEN event_type = 'tiktok' THEN 1 ELSE 0 END) AS tiktok_count,
                    SUM(points) AS total_points
                FROM contest_events
                WHERE guild_id = ? AND occurred_at >= ? AND occurred_at < ?
                GROUP BY user_id
                ORDER BY total_points DESC, tiktok_count DESC, msg_count DESC, react_count DESC
                """,
                (
                    guild_id,
                    start.astimezone(timezone.utc).isoformat(),
                    end.astimezone(timezone.utc).isoformat(),
                ),
            ).fetchall()
            return [
                ContestMemberActivity(
                    user_id=row[0],
                    display_name=row[1],
                    messages=row[2],
                    reactions=row[3],
                    tiktoks=row[4],
                    total_points=row[5],
                )
                for row in rows
            ]

        async with self._lock:
            return await asyncio.to_thread(select)


class EngagementContestCog(commands.Cog, name="EngagementContestCog"):
    """Tracks member engagement in contest channels and publishes the Top 15 Leaderboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = ContestStore(ACTIVITY_DATABASE_PATH)

    async def cog_load(self) -> None:
        await self.store.initialize()
        logger.info("Engagement contest store ready at %s", ACTIVITY_DATABASE_PATH)

    async def cog_unload(self) -> None:
        await self.store.close()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or not is_contest_channel(message.channel):
            return
        if is_excluded_member(message.author):
            return

        has_tiktok = contains_tiktok_link(message.content, message.embeds)
        event_type = "tiktok" if has_tiktok else "message"
        points = CONTEST_POINTS_TIKTOK if has_tiktok else CONTEST_POINTS_MESSAGE

        await self.store.record_events(
            [
                ContestEvent(
                    guild_id=message.guild.id,
                    user_id=message.author.id,
                    user_name=message.author.display_name,
                    channel_id=message.channel.id,
                    event_type=event_type,
                    occurred_at=message.created_at,
                    event_key=f"contest_msg:{message.id}",
                    points=points,
                )
            ]
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or (
            self.bot.user is not None and payload.user_id == self.bot.user.id
        ):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        channel = guild.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(payload.channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return

        if not is_contest_channel(channel):
            return

        member = payload.member
        if member is None:
            member = guild.get_member(payload.user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(payload.user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    return

        if is_excluded_member(member):
            return

        await self.store.record_events(
            [
                ContestEvent(
                    guild_id=payload.guild_id,
                    user_id=payload.user_id,
                    user_name=member.display_name,
                    channel_id=payload.channel_id,
                    event_type="reaction",
                    occurred_at=datetime.now(timezone.utc),
                    event_key=f"contest_reaction:{payload.message_id}:{payload.user_id}:{payload.emoji}",
                    points=CONTEST_POINTS_REACTION,
                )
            ]
        )

    async def backfill_contest_history(
        self, guild: discord.Guild, start: datetime, end: datetime
    ) -> ContestScanStats:
        """Backfills historical activity from the select contest channels and their threads."""
        stats = ContestScanStats()
        member_cache: dict[int, discord.Member | None] = {}

        async def get_member_cached(user_id: int) -> discord.Member | None:
            if user_id in member_cache:
                return member_cache[user_id]
            m = guild.get_member(user_id)
            if m is None:
                try:
                    m = await guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    m = None
            member_cache[user_id] = m
            return m

        async def scan_channel_messages(
            location: discord.TextChannel | discord.Thread,
        ) -> None:
            pending: list[ContestEvent] = []
            try:
                async for message in location.history(
                    limit=None, after=start, before=end, oldest_first=True
                ):
                    stats.messages_scanned += 1
                    author = await get_member_cached(message.author.id)
                    if author is not None and not is_excluded_member(author):
                        has_tiktok = contains_tiktok_link(
                            message.content, message.embeds
                        )
                        if has_tiktok:
                            stats.tiktoks_detected += 1
                            event_type = "tiktok"
                            points = CONTEST_POINTS_TIKTOK
                        else:
                            event_type = "message"
                            points = CONTEST_POINTS_MESSAGE

                        pending.append(
                            ContestEvent(
                                guild_id=guild.id,
                                user_id=author.id,
                                user_name=author.display_name,
                                channel_id=location.id,
                                event_type=event_type,
                                occurred_at=message.created_at,
                                event_key=f"contest_msg:{message.id}",
                                points=points,
                            )
                        )

                    for reaction in message.reactions:
                        try:
                            async for user in reaction.users(limit=None):
                                if user.bot:
                                    continue
                                r_member = await get_member_cached(user.id)
                                if r_member is not None and not is_excluded_member(
                                    r_member
                                ):
                                    stats.reactions_scanned += 1
                                    pending.append(
                                        ContestEvent(
                                            guild_id=guild.id,
                                            user_id=r_member.id,
                                            user_name=r_member.display_name,
                                            channel_id=location.id,
                                            event_type="reaction",
                                            occurred_at=message.created_at,
                                            event_key=(
                                                f"contest_reaction:{message.id}:{user.id}:{reaction.emoji}"
                                            ),
                                            points=CONTEST_POINTS_REACTION,
                                        )
                                    )
                        except (
                            discord.Forbidden,
                            discord.NotFound,
                            discord.HTTPException,
                        ):
                            pass

                    if len(pending) >= 500:
                        await self.store.record_events(pending)
                        pending.clear()

            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                stats.locations_skipped += 1
                logger.warning(
                    "Could not read contest message history in %s", location.id
                )
            finally:
                if pending:
                    await self.store.record_events(pending)

        for channel_id in CONTEST_CHANNEL_IDS:
            channel = guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await guild.fetch_channel(channel_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    stats.locations_skipped += 1
                    continue

            if isinstance(channel, discord.TextChannel):
                await scan_channel_messages(channel)
                stats.channels_scanned += 1

                # Also scan active and archived threads belonging to this channel
                try:
                    for thread in channel.threads:
                        await scan_channel_messages(thread)
                except Exception:
                    pass

                try:
                    async for archived in channel.archived_threads(
                        limit=None, before=end
                    ):
                        if (
                            archived.archive_timestamp
                            and archived.archive_timestamp < start
                        ):
                            break
                        await scan_channel_messages(archived)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass

            elif isinstance(channel, discord.Thread):
                await scan_channel_messages(channel)
                stats.channels_scanned += 1

        logger.info(
            "Contest history scan for guild %s inspected %s messages across %s channels/threads",
            guild.id,
            stats.messages_scanned,
            stats.channels_scanned,
        )
        return stats

    async def publish_contest_leaderboard(
        self,
        *,
        guild: discord.Guild,
        start: datetime,
        end: datetime,
        period_label: str,
        requested_by: discord.Member | discord.User,
    ) -> tuple[discord.abc.Messageable, list[ContestMemberActivity], ContestScanStats]:
        """Scans contest channels, aggregates points, and posts the Top 15 Leaderboard."""
        target_channel_id = CONTEST_REPORT_CHANNEL_ID
        if target_channel_id is None:
            raise RuntimeError("CONTEST_REPORT_CHANNEL_ID is not configured.")

        channel = guild.get_channel(target_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(target_channel_id)
            except discord.NotFound as exc:
                raise RuntimeError(
                    f"Contest report channel {target_channel_id} was not found in this server."
                ) from exc
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise RuntimeError(
                "The configured contest report channel is not a text channel or thread."
            )

        # Backfill history to ensure 100% complete data
        sync_stats = await self.backfill_contest_history(guild, start, end)

        # Aggregate raw events from database
        raw_activities = await self.store.aggregate(guild.id, start, end)

        # Filter out any members who currently have excluded roles or are bots
        qualified_activities: list[ContestMemberActivity] = []
        for activity in raw_activities:
            member = guild.get_member(activity.user_id)
            if member is not None:
                if is_excluded_member(member):
                    continue
                activity.display_name = member.display_name
            qualified_activities.append(activity)

        top_15 = qualified_activities[:15]
        total_participants = len(qualified_activities)
        total_points_sum = sum(act.total_points for act in qualified_activities)
        total_messages_sum = sum(act.messages for act in qualified_activities)
        total_tiktoks_sum = sum(act.tiktoks for act in qualified_activities)
        total_reactions_sum = sum(act.reactions for act in qualified_activities)

        # Build Leaderboard Embed
        embed = discord.Embed(
            title="🏆  CGK Linens — Engagement Contest Leaderboard",
            description=(
                f"{embed_builder.SEPARATOR}\n"
                f"Official contest standings for **{period_label}**.\n\n"
                f"**Scoring System:**\n"
                f"▸ 💬 Messages: **{CONTEST_POINTS_MESSAGE} pts**\n"
                f"▸ 🎬 TikTok Videos: **{CONTEST_POINTS_TIKTOK} pts per post**\n"
                f"▸ ❤️ Reactions: **{CONTEST_POINTS_REACTION} pt**\n"
                f"▸ 🛡️ Excluded: Moderators and Bots\n"
                f"{embed_builder.SEPARATOR}"
            ),
            color=COLOR_ACCENT,
            timestamp=datetime.now(timezone.utc),
        )

        # Target channels preview
        channels_mentions = " ".join(f"<#{cid}>" for cid in sorted(CONTEST_CHANNEL_IDS))
        embed.add_field(
            name=embed_builder.section("Target Channels"),
            value=channels_mentions or "Designated contest channels",
            inline=False,
        )

        # Top 15 Rankings field
        rank_lines: list[str] = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}

        for rank, act in enumerate(top_15, start=1):
            badge = medals.get(rank, "🎖️" if rank <= 10 else "🎗️")
            user_mention = f"<@{act.user_id}>"
            line = (
                f"{badge} **#{rank}** {user_mention} — **`{act.total_points:,}`** pts\n"
                f"   └ 💬 {act.messages:,} msgs ({act.messages * CONTEST_POINTS_MESSAGE:,} pts) • "
                f"🎬 {act.tiktoks:,} TikToks ({act.tiktoks * CONTEST_POINTS_TIKTOK:,} pts) • "
                f"❤️ {act.reactions:,} reacts ({act.reactions * CONTEST_POINTS_REACTION:,} pts)"
            )
            rank_lines.append(line)

        if not rank_lines:
            rank_lines = [
                "No qualifying member engagement was recorded in the select channels for this period."
            ]

        # In case rank lines are long, group into fields
        chunk_size = 8
        if len(rank_lines) <= chunk_size:
            embed.add_field(
                name=embed_builder.section(f"Top {len(top_15)} Leaderboard"),
                value="\n".join(rank_lines),
                inline=False,
            )
        else:
            embed.add_field(
                name=embed_builder.section(f"Top Leaderboard (1-{min(chunk_size, len(rank_lines))})"),
                value="\n".join(rank_lines[:chunk_size]),
                inline=False,
            )
            embed.add_field(
                name=embed_builder.section(f"Top Leaderboard ({chunk_size + 1}-{len(rank_lines)})"),
                value="\n".join(rank_lines[chunk_size:]),
                inline=False,
            )

        # Summary statistics
        embed.add_field(
            name=embed_builder.section("Contest Summary"),
            value=(
                f"▸ **Total Points Awarded:** `{total_points_sum:,}`\n"
                f"▸ **Qualifying Participants:** `{total_participants:,}`\n"
                f"▸ **Messages Counted:** `{total_messages_sum:,}`\n"
                f"▸ **TikTok Video Posts:** `{total_tiktoks_sum:,}`\n"
                f"▸ **Reactions Counted:** `{total_reactions_sum:,}`\n"
                f"▸ **Channels Inspected:** `{sync_stats.channels_scanned:,}`"
            ),
            inline=False,
        )

        embed.set_footer(text=f"{EMBED_FOOTER_TEXT} • Requested by {requested_by.display_name}")

        await channel.send(
            content=(
                f"🏆 **CGK Linens Engagement Contest Leaderboard**\n"
                f"Period: **{period_label}** • Generated by {requested_by.mention}"
            ),
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

        logger.info(
            "Published contest leaderboard for guild %s to channel %s covering %s to %s",
            guild.id,
            channel.id,
            start,
            end,
        )
        return channel, top_15, sync_stats


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EngagementContestCog(bot))
