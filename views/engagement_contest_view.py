"""
Moderator UI for launching and configuring the Engagement Contest Leaderboard.
Created by Aljay Leodones for CGK Linens.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord

from config import CONTEST_REPORT_CHANNEL_ID, REPORT_TIMEZONE
from utils import embed_builder

logger = logging.getLogger("cgk_bot.contest_ui")


def _report_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(REPORT_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown REPORT_TIMEZONE %r; falling back to UTC", REPORT_TIMEZONE)
        return ZoneInfo("UTC")


def _can_manage(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


def get_today_range() -> tuple[datetime, datetime, str]:
    """Calculates range from midnight today (in REPORT_TIMEZONE) to the current moment."""
    tz = _report_timezone()
    now_local = datetime.now(tz)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    now_utc = datetime.now(timezone.utc)
    start_utc = start_local.astimezone(timezone.utc)
    return (
        start_utc,
        now_utc,
        f"Starting Today ({now_local.strftime('%B %d, %Y')} • {REPORT_TIMEZONE})",
    )


def _parse_custom_contest_range(
    start_text: str, end_text: str
) -> tuple[datetime, datetime]:
    tz = _report_timezone()

    def parse(value: str, *, is_end: bool) -> datetime:
        clean_value = value.strip()
        if not clean_value and is_end:
            return datetime.now(tz)
        try:
            parsed = datetime.strptime(clean_value, "%Y-%m-%d %H:%M")
            return parsed.replace(tzinfo=tz)
        except ValueError:
            pass
        try:
            parsed_date = datetime.strptime(clean_value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(
                "Use YYYY-MM-DD or YYYY-MM-DD HH:MM for both dates."
            ) from exc
        parsed = datetime.combine(parsed_date, time.min, tzinfo=tz)
        return parsed + timedelta(days=1) if is_end else parsed

    start = parse(start_text, is_end=False)
    end = parse(end_text, is_end=True)
    if end <= start:
        raise ValueError("The end date/time must be after the start date/time.")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def _run_contest_publish(
    interaction: discord.Interaction,
    *,
    start: datetime,
    end: datetime,
    period_label: str,
) -> None:
    if interaction.guild is None:
        await interaction.followup.send(
            "Engagement contest reports can only be generated inside a server.",
            ephemeral=True,
        )
        return

    cog = interaction.client.get_cog("EngagementContestCog")
    if cog is None:
        await interaction.followup.send(
            "The engagement contest module is not ready. Check bot logs.",
            ephemeral=True,
        )
        return

    try:
        channel, top_rows, sync_stats = await cog.publish_contest_leaderboard(
            guild=interaction.guild,
            start=start,
            end=end,
            period_label=period_label,
            requested_by=interaction.user,
        )
    except (RuntimeError, discord.Forbidden, discord.HTTPException) as exc:
        logger.exception("Could not publish engagement contest leaderboard")
        await interaction.followup.send(
            f"The contest leaderboard could not be published: {exc}", ephemeral=True
        )
        return
    except Exception:
        logger.exception("Unexpected contest leaderboard failure")
        await interaction.followup.send(
            "The contest history scan failed unexpectedly. Check the bot console for details.",
            ephemeral=True,
        )
        return

    first_place = f"🥇 Winner: **{top_rows[0].display_name}** ({top_rows[0].total_points:,} pts)" if top_rows else "No active participants"
    await interaction.followup.send(
        f"✅ **Engagement Contest Leaderboard published in {channel.mention}!**\n"
        f"▸ Evaluated Top {len(top_rows)} participant(s)\n"
        f"▸ {first_place}\n"
        f"▸ Inspected {sync_stats.messages_scanned:,} historical messages across {sync_stats.channels_scanned:,} contest channel(s)/thread(s).",
        ephemeral=True,
    )


class CustomContestDateModal(discord.ui.Modal, title="Custom Contest Date Range"):
    start_date = discord.ui.TextInput(
        label=f"Start date/time ({REPORT_TIMEZONE})",
        placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM",
        min_length=10,
        max_length=16,
    )
    end_date = discord.ui.TextInput(
        label=f"End date/time ({REPORT_TIMEZONE})",
        placeholder="YYYY-MM-DD or YYYY-MM-DD HH:MM (blank for now)",
        min_length=0,
        max_length=16,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not _can_manage(interaction):
            await interaction.response.send_message(
                "You need the Manage Server permission to launch contest leaderboards.",
                ephemeral=True,
            )
            return
        try:
            start, end = _parse_custom_contest_range(
                self.start_date.value, self.end_date.value
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        period_label = (
            f"Custom: {self.start_date.value.strip()} to "
            f"{self.end_date.value.strip() or 'Now'} ({REPORT_TIMEZONE})"
        )
        await _run_contest_publish(
            interaction, start=start, end=end, period_label=period_label
        )


class EngagementContestRangeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Select contest evaluation period...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Starting Today",
                    value="today",
                    emoji="📅",
                    description=f"Since 12:00 AM today ({REPORT_TIMEZONE})",
                ),
                discord.SelectOption(
                    label="Past 24 Hours",
                    value="24h",
                    emoji="⏱️",
                    description="Last 24 hours from right now",
                ),
                discord.SelectOption(
                    label="Past 7 Days",
                    value="7d",
                    emoji="🗓️",
                    description="Last 7 days",
                ),
                discord.SelectOption(
                    label="Past 14 Days",
                    value="14d",
                    emoji="📆",
                    description="Last 14 days",
                ),
                discord.SelectOption(
                    label="Past 30 Days",
                    value="30d",
                    emoji="📊",
                    description="Last 30 days",
                ),
                discord.SelectOption(
                    label="Custom Date Range",
                    value="custom",
                    emoji="⚙️",
                    description="Specify custom start and end dates",
                ),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not _can_manage(interaction):
            await interaction.response.send_message(
                "You need the Manage Server permission to launch contest leaderboards.",
                ephemeral=True,
            )
            return

        selection = self.values[0]
        if selection == "custom":
            await interaction.response.send_modal(CustomContestDateModal())
            return

        now_utc = datetime.now(timezone.utc)
        if selection == "today":
            start, end, label = get_today_range()
        elif selection == "24h":
            start = now_utc - timedelta(hours=24)
            end = now_utc
            label = "Past 24 Hours"
        elif selection == "7d":
            start = now_utc - timedelta(days=7)
            end = now_utc
            label = "Past 7 Days"
        elif selection == "14d":
            start = now_utc - timedelta(days=14)
            end = now_utc
            label = "Past 14 Days"
        elif selection == "30d":
            start = now_utc - timedelta(days=30)
            end = now_utc
            label = "Past 30 Days"
        else:
            await interaction.response.send_message("Invalid option.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await _run_contest_publish(
            interaction, start=start, end=end, period_label=label
        )


class EngagementContestRangeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)
        self.add_item(EngagementContestRangeSelect())


def build_contest_prompt_embed() -> discord.Embed:
    """Builds the prompt embed when clicking Engagement Contest on Mod Panel."""
    dest = (
        f"<#{CONTEST_REPORT_CHANNEL_ID}>"
        if CONTEST_REPORT_CHANNEL_ID
        else "the configured channel"
    )
    embed = embed_builder.base_embed(
        title="🏆  Engagement Contest Leaderboard",
        description=(
            f"{embed_builder.SEPARATOR}\n"
            "Select the contest timeframe to evaluate. The bot will scan messages, "
            "reactions, and TikTok links in the designated channels.\n\n"
            "**Contest Rules & Weighting:**\n"
            "▸ 💬 Messages: **3 points**\n"
            "▸ 🎬 TikTok Links (`https://www.tiktok.com/`): **5 points per post**\n"
            "▸ ❤️ Reactions: **1 point**\n"
            "▸ 🛡️ Excluded: Moderators and Bots\n\n"
            f"The **Top 15 Leaderboard** will be posted to {dest}."
        ),
        color=embed_builder.COLOR_ACCENT,
    )
    return embed
