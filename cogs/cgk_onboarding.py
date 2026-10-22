"""
CGK Onboarding engine: one private onboarding channel per new member.
Created by Aljay Leodones for CGK Linens.

A moderator scans for recent members, picks the join days, and the bot opens
a ticket-style ``#<handle>-onboarding`` channel for each of them in the
onboarding category. Only that member and the server's moderators can see
it. The member is tagged there with the creator questions (✅ YES / ❌ NO,
then 🌱 / 🔥), the community rules and the Slack-connected questionnaire.
Submitting the questionnaire grants the access role that unlocks the rest
of the server. Only members with the designated moderator role can use the
🔒 Close onboarding button, which deletes the channel.

Every send is remembered as one "tagged group", so the most recent group can
be cleared and tagged again from the scan screen.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import re
import time
from typing import Awaitable, Callable, Optional

import discord
from discord.ext import commands

from cogs.creator_onboarding import WELCOME_MESSAGE
from cogs.onboarding import DayGroup, group_by_day, recent_members
from config import (
    COMMUNITY_DATABASE_PATH,
    CGK_ONBOARDING_CATEGORY_ID,
    CGK_ONBOARDING_ROLE_ID,
)
from core.database import get_database

logger = logging.getLogger("cgk_bot.cgk_onboarding")

# Posted above the creator question in every onboarding channel.
TICKET_INTRO = (
    "{mention} 🔒 This is your private onboarding channel — only you and the "
    "CGK team can see it. **Finish the onboarding below to unlock all of the "
    "server's channels.** Got a question along the way? Just type it here and "
    "the team will reply."
)
TOPIC_TEMPLATE = "Private CGK onboarding for {member} · member ID {member_id}"
_TOPIC_OWNER = re.compile(r"member ID (\d+)")

SETTING_KEYS = {
    "category": "cgk_onboarding_category_id",
    "role": "cgk_onboarding_role_id",
}
ENV_DEFAULTS = {
    "category": CGK_ONBOARDING_CATEGORY_ID,
    "role": CGK_ONBOARDING_ROLE_ID,
}

# Discord allows at most 50 channels in one category.
CATEGORY_LIMIT = 50
CREATE_PACE_SECONDS = 1.0
PROGRESS_EVERY = 5
ONBOARDING_MODERATOR_ROLE_ID = 1542915539872125049
# The old Onboarding role. New members no longer get it, but anyone who still
# holds it loses it on completion.
ONBOARDING_PENDING_ROLE_ID = 1559649034598227968

# Auto onboarding (Mod Panel -> Auto Onboarding): while it is ON, every member
# who joins gets this role, loses sight of the hidden channel, and is sent
# straight into their own private onboarding channel. Finishing onboarding
# removes the role and shows the channel again.
AUTO_ONBOARDING_ROLE_ID = 1562894069544255489
AUTO_HIDDEN_CHANNEL_ID = 1377020906987065416
AUTO_ONBOARDING_SETTING = "cgk_auto_onboarding"
# The tagged group for members whose channel opened when they joined, so
# scans skip them but "clear last tagged group" never picks them up.
AUTO_JOIN_BATCH = 0
# Roles that are taken away once a member finishes onboarding.
TEMPORARY_ROLE_IDS = (AUTO_ONBOARDING_ROLE_ID, ONBOARDING_PENDING_ROLE_ID)

# Roles with any of these can moderate, so they can see every onboarding channel.
STAFF_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_channels",
    "manage_messages",
    "moderate_members",
)

ProgressCallback = Callable[[int, int], Awaitable[None]]


class CategoryFull(Exception):
    """The onboarding category already holds Discord's maximum of 50 channels."""


@dataclass(slots=True)
class CGKSettings:
    category_id: int | None
    role_id: int | None
    # Where each value came from: "saved" (Mod Panel), "env" or "unset".
    sources: dict[str, str]


@dataclass(slots=True)
class TaggedGroup:
    batch_id: int
    count: int
    tagged_at: float


@dataclass(slots=True)
class TicketResult:
    created: list[discord.TextChannel] = field(default_factory=list)
    reused: list[discord.TextChannel] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (member, reason)
    member_ids: list[int] = field(default_factory=list)  # everyone tagged in a channel

    @property
    def opened(self) -> int:
        return len(self.created) + len(self.reused)


def channel_name(member: discord.abc.User) -> str:
    """``lemon`` -> ``lemon-onboarding`` (Discord's channel-name rules)."""
    base = re.sub(r"[^a-z0-9_-]+", "-", (member.name or "").lower()).strip("-_")
    return f"{base[:80] or f'member-{member.id}'}-onboarding"


def owner_from_topic(topic: str | None) -> int | None:
    match = _TOPIC_OWNER.search(topic or "")
    return int(match.group(1)) if match else None


def is_staff_role(role: discord.Role) -> bool:
    if role.is_default() or role.managed:
        return False
    permissions = role.permissions
    return any(getattr(permissions, name, False) for name in STAFF_PERMISSIONS)


def can_close(
    member: discord.Member, channel: discord.abc.GuildChannel, owner_id: int | None
) -> bool:
    """Only the designated moderator role can close an onboarding channel."""
    return owner_id is not None and any(
        role.id == ONBOARDING_MODERATOR_ROLE_ID for role in getattr(member, "roles", ())
    )


def ticket_overwrites(
    guild: discord.Guild, member: discord.Member
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    """Hidden from everyone except the member, the moderators and the bot."""
    staff = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, read_message_history=True
    )
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        role: staff for role in guild.roles if is_staff_role(role)
    }
    overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
    overwrites[member] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        embed_links=True,
    )
    overwrites[guild.me] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        embed_links=True,
        manage_channels=True,
    )
    return overwrites


class CGKOnboardingCog(commands.Cog, name="CGKOnboardingCog"):
    """Opens private onboarding channels and grants access on completion."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._self_service_lock = asyncio.Lock()
        self.db = get_database(COMMUNITY_DATABASE_PATH)

    async def cog_load(self) -> None:
        await self.db.initialize()
        logger.info("CGK onboarding ready")

    # -- settings ----------------------------------------------
    async def settings(self, guild_id: int) -> CGKSettings:
        stored = await self.db.get_settings(guild_id, list(SETTING_KEYS.values()))
        values: dict[str, int | None] = {}
        sources: dict[str, str] = {}
        for key, setting in SETTING_KEYS.items():
            raw = stored.get(setting)
            if raw and raw.isdigit():
                values[key], sources[key] = int(raw), "saved"
            elif ENV_DEFAULTS[key]:
                values[key], sources[key] = ENV_DEFAULTS[key], "env"
            else:
                values[key], sources[key] = None, "unset"
        return CGKSettings(values["category"], values["role"], sources)

    async def set_value(self, guild_id: int, key: str, value: int | None) -> None:
        await self.db.set_setting(guild_id, SETTING_KEYS[key], str(value) if value else None)

    @staticmethod
    def category(guild: discord.Guild, settings: CGKSettings) -> discord.CategoryChannel | None:
        channel = guild.get_channel(settings.category_id) if settings.category_id else None
        return channel if isinstance(channel, discord.CategoryChannel) else None

    @staticmethod
    def role(guild: discord.Guild, settings: CGKSettings) -> discord.Role | None:
        return guild.get_role(settings.role_id) if settings.role_id else None

    def setup_problems(self, guild: discord.Guild, settings: CGKSettings) -> list[str]:
        """Everything that would stop channels being opened or access granted."""
        problems: list[str] = []
        me = guild.me
        category = self.category(guild, settings)
        if category is None:
            problems.append("The onboarding **category** was not found — pick one in ⚙️ Settings.")
        elif not category.permissions_for(me).manage_channels:
            problems.append(f"The bot needs **Manage Channels** in the **{category.name}** category.")
        if not me.guild_permissions.manage_roles:
            problems.append("The bot needs the **Manage Roles** permission.")
        role = self.role(guild, settings)
        if role is None:
            problems.append("The **access role** was not found — pick one in ⚙️ Settings.")
        elif role >= me.top_role:
            problems.append(
                f"Move the bot's role **above** {role.mention} in Server Settings → Roles, "
                "so it can hand that role out."
            )
        if role is not None and role.id in TEMPORARY_ROLE_IDS:
            problems.append("Choose an access role other than the **Onboarding** role.")
        for temporary_id in TEMPORARY_ROLE_IDS:
            temporary = guild.get_role(temporary_id)
            if temporary is not None and (temporary.managed or temporary >= me.top_role):
                problems.append(
                    f"The bot must be above {temporary.mention}, and that role must "
                    "be editable, so it can be removed on completion."
                )
        return problems

    # -- auto onboarding ---------------------------------------
    async def auto_enabled(self, guild_id: int) -> bool:
        return await self.db.get_setting(guild_id, AUTO_ONBOARDING_SETTING) == "1"

    async def set_auto_enabled(self, guild_id: int, enabled: bool) -> None:
        await self.db.set_setting(guild_id, AUTO_ONBOARDING_SETTING, "1" if enabled else "0")

    def auto_problems(self, guild: discord.Guild, settings: CGKSettings) -> list[str]:
        """Everything that would stop a new member being onboarded on join."""
        problems = self.setup_problems(guild, settings)
        if guild.get_role(AUTO_ONBOARDING_ROLE_ID) is None:
            problems.append(f"The onboarding role `{AUTO_ONBOARDING_ROLE_ID}` was not found.")
        hidden = guild.get_channel(AUTO_HIDDEN_CHANNEL_ID)
        if hidden is None:
            problems.append(f"The channel to hide (`{AUTO_HIDDEN_CHANNEL_ID}`) was not found.")
        elif not hidden.permissions_for(guild.me).manage_roles:
            problems.append(
                f"The bot needs **Manage Permissions** in {hidden.mention} to hide it "
                "from new members."
            )
        return problems

    async def _set_hidden(self, member: discord.Member, hidden: bool) -> None:
        """Hides the hidden channel from one member, or removes that override."""
        channel = member.guild.get_channel(AUTO_HIDDEN_CHANNEL_ID)
        if channel is None:
            return
        if hidden:
            await channel.set_permissions(
                member, view_channel=False, reason="Auto onboarding: new member"
            )
        elif not channel.overwrites_for(member).is_empty():
            await channel.set_permissions(
                member, overwrite=None, reason="Auto onboarding: finished or left"
            )

    async def auto_onboard(self, member: discord.Member) -> discord.TextChannel | None:
        """Role, hidden channel and private channel for a member who just joined."""
        from views.creator_onboarding_view import OnboardingTicketView

        guild = member.guild
        role = guild.get_role(AUTO_ONBOARDING_ROLE_ID)
        if role is None:
            logger.warning("Auto onboarding role %s is missing in %s", AUTO_ONBOARDING_ROLE_ID, guild.id)
        else:
            try:
                await member.add_roles(role, reason="Auto onboarding: new member")
            except discord.HTTPException as exc:
                logger.warning("Could not give %s the onboarding role: %s", member.id, exc)
        try:
            await self._set_hidden(member, True)
        except discord.HTTPException as exc:
            logger.warning("Could not hide %s from %s: %s", AUTO_HIDDEN_CHANNEL_ID, member.id, exc)

        category = self.category(guild, await self.settings(guild.id))
        if category is None:
            logger.warning("Auto onboarding in %s: the onboarding category is missing", guild.id)
            return None
        try:
            async with self._self_service_lock:
                channel = await self._ticket_channel(guild, member.id)
                if channel is not None:
                    return channel
                channel, _ = await self.open_ticket(
                    member, category, OnboardingTicketView(),
                    batch_id=AUTO_JOIN_BATCH, tagged_by=None,
                )
        except CategoryFull:
            logger.warning("Auto onboarding in %s: the category is full", guild.id)
            return None
        except discord.HTTPException as exc:
            logger.warning("Could not open an onboarding channel for %s: %s", member.id, exc)
            return None
        logger.info("Auto onboarding opened %s for %s", channel.id, member.id)
        return channel

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        try:
            if await self.auto_enabled(member.guild.id):
                await self.auto_onboard(member)
        except Exception:  # noqa: BLE001 - a join must never crash the bot
            logger.exception("Auto onboarding failed for %s", member.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Clears the hidden-channel override left by a member who never finished."""
        if not any(role.id == AUTO_ONBOARDING_ROLE_ID for role in member.roles):
            return
        try:
            await self._set_hidden(member, False)
        except Exception:  # noqa: BLE001 - bookkeeping only
            logger.warning("Could not clear the hidden channel for %s", member.id, exc_info=True)

    # -- records -----------------------------------------------
    async def tagged_ids(self, guild_id: int) -> set[int]:
        rows = await self.db.fetchall(
            "SELECT user_id FROM cgk_onboarding_members "
            "WHERE guild_id = ? AND batch_id IS NOT NULL",
            (guild_id,),
        )
        return {row["user_id"] for row in rows}

    async def pending_members(
        self, guild: discord.Guild, settings: CGKSettings | None = None
    ) -> list[discord.Member]:
        """Recent members never tagged who still hold an Onboarding role and lack access."""
        settings = settings or await self.settings(guild.id)
        members = await recent_members(guild, await self.tagged_ids(guild.id))
        role_id = settings.role_id
        return [
            m
            for m in members
            if any(r.id in TEMPORARY_ROLE_IDS for r in m.roles)
            and not any(r.id == role_id for r in m.roles)
        ]

    def group_by_day(self, members: list[discord.Member]) -> list[DayGroup]:
        return group_by_day(members)

    async def last_group(self, guild_id: int) -> TaggedGroup | None:
        row = await self.db.fetchone(
            """
            SELECT batch_id, COUNT(*) AS total, MAX(tagged_at) AS tagged_at
            FROM cgk_onboarding_members
            WHERE guild_id = ? AND batch_id IS NOT NULL AND batch_id != ?
            GROUP BY batch_id ORDER BY MAX(tagged_at) DESC LIMIT 1
            """,
            (guild_id, AUTO_JOIN_BATCH),
        )
        if row is None:
            return None
        return TaggedGroup(row["batch_id"], row["total"], row["tagged_at"] or 0.0)

    async def clear_last_group(self, guild_id: int) -> int:
        """Untags the most recent group so those members can be tagged again."""
        group = await self.last_group(guild_id)
        if group is None:
            return 0
        await self.db.execute(
            "UPDATE cgk_onboarding_members SET batch_id = NULL, tagged_at = NULL "
            "WHERE guild_id = ? AND batch_id = ?",
            (guild_id, group.batch_id),
        )
        return group.count

    async def owner_of(self, channel: discord.abc.GuildChannel | discord.Thread | None) -> int | None:
        """The member a CGK onboarding channel belongs to, or `None`."""
        if channel is None:
            return None
        owner = owner_from_topic(getattr(channel, "topic", None))
        if owner is not None:
            return owner
        row = await self.db.fetchone(
            "SELECT user_id FROM cgk_onboarding_members WHERE guild_id = ? AND channel_id = ?",
            (channel.guild.id, channel.id),
        )
        return row["user_id"] if row else None

    async def _ticket_channel(self, guild: discord.Guild, user_id: int) -> discord.TextChannel | None:
        row = await self.db.fetchone(
            "SELECT channel_id FROM cgk_onboarding_members WHERE guild_id = ? AND user_id = ?",
            (guild.id, user_id),
        )
        channel = guild.get_channel(row["channel_id"]) if row and row["channel_id"] else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _save_ticket(
        self,
        guild_id: int,
        user_id: int,
        channel_id: int,
        *,
        batch_id: int | None,
        tagged_by: int | None,
    ) -> None:
        """Remembers the channel; a test run (no batch) leaves the tag alone."""
        tagged_at = time.time() if batch_id is not None else None
        await self.db.execute(
            """
            INSERT INTO cgk_onboarding_members
                (user_id, guild_id, channel_id, batch_id, tagged_at, tagged_by)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                batch_id = COALESCE(excluded.batch_id, batch_id),
                tagged_at = COALESCE(excluded.tagged_at, tagged_at),
                tagged_by = COALESCE(excluded.tagged_by, tagged_by)
            """,
            (user_id, guild_id, channel_id, batch_id, tagged_at, tagged_by),
        )

    # -- opening channels --------------------------------------
    async def open_ticket(
        self,
        member: discord.Member,
        category: discord.CategoryChannel,
        view: discord.ui.View,
        *,
        batch_id: int | None,
        tagged_by: int | None,
    ) -> tuple[discord.TextChannel, bool]:
        """
        Opens (or reuses) the member's onboarding channel and tags them in it.

        Returns the channel and whether it was newly created. A member tagged
        again gets the welcome re-posted in the channel they already have.
        """
        guild = member.guild
        channel = await self._ticket_channel(guild, member.id)
        created = channel is None
        if channel is None:
            if len(category.channels) >= CATEGORY_LIMIT:
                raise CategoryFull()
            channel = await guild.create_text_channel(
                channel_name(member),
                category=category,
                overwrites=ticket_overwrites(guild, member),
                topic=TOPIC_TEMPLATE.format(member=member, member_id=member.id),
                reason=f"CGK onboarding for {member} ({member.id})",
            )
        await self._save_ticket(
            guild.id, member.id, channel.id, batch_id=batch_id, tagged_by=tagged_by
        )
        await channel.send(
            content=f"{TICKET_INTRO.format(mention=member.mention)}\n\n{WELCOME_MESSAGE}",
            view=view,
            allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False),
        )
        return channel, created

    async def start_self_service(
        self, member: discord.Member, category: discord.CategoryChannel, view: discord.ui.View
    ) -> tuple[discord.TextChannel, bool]:
        """Reuse the current flow without posting duplicate welcomes on repeat clicks."""
        async with self._self_service_lock:
            channel = await self._ticket_channel(member.guild, member.id)
            if channel is not None:
                return channel, False
            return await self.open_ticket(
                member, category, view, batch_id=None, tagged_by=None
            )

    async def deliver(
        self,
        *,
        guild: discord.Guild,
        members: list[discord.Member],
        moderator: discord.abc.User,
        batch_id: int,
        view_factory: Callable[[], discord.ui.View],
        progress: Optional[ProgressCallback] = None,
    ) -> TicketResult:
        """Opens an onboarding channel for every member, paced for rate limits."""
        settings = await self.settings(guild.id)
        category = self.category(guild, settings)
        if category is None:
            raise ValueError("The onboarding category was not found.")
        result = TicketResult()
        total = len(members)
        for index, member in enumerate(members, start=1):
            try:
                channel, created = await self.open_ticket(
                    member, category, view_factory(), batch_id=batch_id, tagged_by=moderator.id
                )
            except CategoryFull:
                result.failed.append((member.display_name, "category is full (50 channels)"))
            except discord.Forbidden:
                result.failed.append((member.display_name, "missing permissions"))
            except discord.HTTPException as exc:
                result.failed.append((member.display_name, str(exc.text or exc)[:80]))
            else:
                (result.created if created else result.reused).append(channel)
                result.member_ids.append(member.id)
            if progress is not None and index % PROGRESS_EVERY == 0 and index < total:
                try:
                    await progress(index, total)
                except discord.HTTPException:
                    progress = None  # The token expired; keep going regardless.
            if index < total:
                await asyncio.sleep(CREATE_PACE_SECONDS)
        logger.info(
            "CGK onboarding in guild %s: %s created, %s reused, %s failed",
            guild.id, len(result.created), len(result.reused), len(result.failed),
        )
        return result

    # -- closing -----------------------------------------------
    async def forget_channel(self, guild_id: int, channel_id: int) -> None:
        """Drops a deleted channel, so tagging that member again opens a new one."""
        await self.db.execute(
            "UPDATE cgk_onboarding_members SET channel_id = NULL "
            "WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )

    async def close_ticket(
        self, channel: discord.TextChannel, *, closed_by: discord.abc.User
    ) -> None:
        """Deletes an onboarding channel when requested by an authorized moderator."""
        if not can_close(closed_by, channel, await self.owner_of(channel)):
            raise PermissionError("Only the designated moderators can close onboarding channels.")
        await channel.delete(reason=f"Onboarding channel closed by {closed_by} ({closed_by.id})")
        await self.forget_channel(channel.guild.id, channel.id)
        logger.info("Onboarding channel %s closed by %s", channel.id, closed_by.id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """A channel deleted by hand in Discord is forgotten too."""
        try:
            await self.forget_channel(channel.guild.id, channel.id)
        except Exception:  # noqa: BLE001 - bookkeeping only
            logger.warning("Could not forget deleted channel %s", channel.id, exc_info=True)

    # -- completion --------------------------------------------
    async def complete(self, member: discord.Member) -> bool:
        """
        Grants the access role, takes the Onboarding roles away and shows the
        hidden channel again, then logs completion. False if it could not.
        """
        guild = member.guild
        settings = await self.settings(guild.id)
        role = self.role(guild, settings)
        if role is None or role.id in TEMPORARY_ROLE_IDS:
            logger.warning("CGK onboarding access role %s is missing or invalid", settings.role_id)
            return False
        try:
            if role not in member.roles:
                await member.add_roles(role, reason="Completed CGK onboarding")
            for temporary in [r for r in member.roles if r.id in TEMPORARY_ROLE_IDS]:
                await member.remove_roles(temporary, reason="Completed CGK onboarding")
        except discord.HTTPException as exc:
            logger.warning("Could not update onboarding roles for %s: %s", member.id, exc)
            return False
        try:
            await self._set_hidden(member, False)
        except discord.HTTPException as exc:
            logger.warning("Could not show %s to %s again: %s", AUTO_HIDDEN_CHANNEL_ID, member.id, exc)
        await self.db.execute(
            """
            INSERT INTO cgk_onboarding_members (user_id, guild_id, completed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET completed_at = excluded.completed_at
            """,
            (member.id, guild.id, time.time()),
        )
        return True

    async def stats(self, guild: discord.Guild) -> dict[str, int]:
        row = await self.db.fetchone(
            """
            SELECT SUM(channel_id IS NOT NULL) AS channels,
                   SUM(batch_id IS NOT NULL) AS tagged,
                   SUM(completed_at IS NOT NULL) AS completed
            FROM cgk_onboarding_members WHERE guild_id = ?
            """,
            (guild.id,),
        )
        pending = await self.pending_members(guild)

        def value(key: str) -> int:
            return (row[key] if row else 0) or 0

        return {
            "pending": len(pending),
            "channels": value("channels"),
            "tagged": value("tagged"),
            "completed": value("completed"),
        }


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CGKOnboardingCog(bot))
