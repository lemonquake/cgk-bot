"""
Persistent Mod Panel View for the CGK Linens Discord Bot.
Created by Aljay Leodones for CGK Linens.
"""

from __future__ import annotations

import logging

import discord

from config import BRAND_NAME, ONBOARDING_LOOKBACK_DAYS
from core.announcements import ANNOUNCEMENTS, get_announcement_store
from utils import embed_builder
from views.announcement_view import open_announcements
from views.broadcast_view import PlainMessageModal
from views.common import require_manage
from views.embed_studio_view import open_studio
from views.engagement_contest_view import (
    EngagementContestRangeView,
    build_contest_prompt_embed,
)
from views.engagement_report_view import EngagementRangeView
from views.member_report_view import MemberReportHubView, build_report_hub_embed
from views.onboarding_view import OnboardingHubView, build_hub_embed

logger = logging.getLogger("cgk_bot.mod_panel_ui")

FUNCTION_GUIDE = [
    ("👋 Onboarding", "Welcome new members — pick which join days, post and DM."),
    ("📊 Community Reports", "Growth reports that refresh themselves in a channel."),
    ("📈 Engagement Report", "Rank members by messages, reactions and threads."),
    ("🏆 Engagement Contest", "Top 15 contest leaderboard in select channels with TikTok & point weighting."),
    ("📣 CGK Discord Announcement", "The four weekly posts — edit, publish or schedule them."),
    ("📝 Embed Message", "Compose, save and reuse branded embeds — templates included."),
    ("💬 Normal Message", "Send a plain text message through the bot."),
    ("🔄 Refresh Dashboard", "Reload this panel with the latest data and buttons."),
]


async def build_mod_panel_embed(
    bot: discord.Client, guild: discord.Guild | None = None
) -> discord.Embed:
    """Builds the Mod Panel embed with live server, module and health data."""
    latency_ms = round(bot.latency * 1000) if bot.latency else 0
    onboarding_cog = bot.get_cog("OnboardingCog")
    report_cog = bot.get_cog("MemberReportCog")
    engagement_cog = bot.get_cog("EngagementCog")
    contest_cog = bot.get_cog("EngagementContestCog")

    embed = embed_builder.base_embed(
        title=f"{BRAND_NAME} — Management Panel",
        description=(
            f"{embed_builder.SEPARATOR}\n"
            "Everything the team needs in one place. Every button below stays "
            "usable after a restart — this panel never has to be re-summoned."
        ),
    )
    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    guild_name = guild.name if guild else "Unknown server"
    member_count = (
        f"{guild.member_count:,}" if guild and guild.member_count else "n/a"
    )
    embed.add_field(
        name=embed_builder.section("Server"),
        value=(
            embed_builder.item(f"Name: **{guild_name}**")
            + "\n"
            + embed_builder.item(f"Members: **{member_count}**")
        ),
        inline=True,
    )
    embed.add_field(
        name=embed_builder.section("Connection"),
        value=(
            f"{embed_builder.item('Status: **Online**')}\n"
            f"{embed_builder.item(f'Latency: **{latency_ms}ms**')}"
        ),
        inline=True,
    )

    if guild is not None and onboarding_cog is not None:
        try:
            stats = await onboarding_cog.onboarding_stats(guild)
            pending = stats["pending"]
            welcomed = stats["total"]
            embed.add_field(
                name=embed_builder.section("Onboarding"),
                value="\n".join(
                    [
                        embed_builder.item(f"Waiting for a welcome: **{pending}**"),
                        embed_builder.item(f"Welcomed all-time: **{welcomed}**"),
                        embed_builder.item(
                            f"Scan window: last **{ONBOARDING_LOOKBACK_DAYS}** days"
                        ),
                    ]
                ),
                inline=False,
            )
        except RuntimeError:
            logger.warning("Onboarding statistics were not ready for the panel")

    if guild is not None and report_cog is not None:
        try:
            reports = await report_cog.list_reports(guild.id)
            summary = (
                "\n".join(
                    embed_builder.item(
                        f"**{row['label'] or row['timeframe']}** in <#{row['channel_id']}>"
                    )
                    for row in reports
                )
                if reports
                else embed_builder.item("No live community report deployed yet.")
            )
            embed.add_field(
                name=embed_builder.section("Live community reports"),
                value=summary,
                inline=False,
            )
        except RuntimeError:
            logger.warning("Report list was not ready for the panel")

    if guild is not None:
        try:
            schedules = await get_announcement_store().list_schedules(guild.id)
        except Exception:  # noqa: BLE001 - the panel must still render
            logger.warning("Announcement schedules were not ready for the panel")
        else:
            lines = [
                embed_builder.item(
                    f"**{announcement.label}** — "
                    + (
                        schedules[announcement.slug].describe()
                        if announcement.slug in schedules
                        else "not scheduled"
                    )
                )
                for announcement in ANNOUNCEMENTS
            ]
            embed.add_field(
                name=embed_builder.section("Weekly announcements"),
                value="\n".join(lines),
                inline=False,
            )

    embed.add_field(
        name=embed_builder.section("What each button does"),
        value="\n".join(
            embed_builder.item(f"**{label}** — {description}")
            for label, description in FUNCTION_GUIDE
        ),
        inline=False,
    )

    embed.add_field(
        name=embed_builder.section("System health"),
        value=embed_builder.status_block(
            {
                "Onboarding module": "ready" if onboarding_cog else "unavailable",
                "Community reporting": "ready" if report_cog else "unavailable",
                "Engagement tracking": "ready" if engagement_cog else "unavailable",
                "Contest tracking": "ready" if contest_cog else "unavailable",
                "Persistent controls": "enabled",
            }
        ),
        inline=False,
    )
    return embed


class ModPanelView(discord.ui.View):
    """
    Persistent view for the moderator dashboard.

    `timeout=None` plus static `custom_id`s keep every button alive across
    restarts, so the panel only ever has to be summoned once.
    """

    def __init__(self):
        super().__init__(timeout=None)

    # ── Row 0: community tools ────────────────────────────────
    @discord.ui.button(
        label="Onboarding",
        style=discord.ButtonStyle.success,
        custom_id="cgk_mod_panel:onboarding",
        emoji="👋",
        row=0,
    )
    async def onboarding_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the onboarding hub (scan, day picker, channel setup)."""
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            embed=await build_hub_embed(interaction),
            view=OnboardingHubView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Community Reports",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_mod_panel:community_report",
        emoji="📊",
        row=0,
    )
    async def community_report_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the growth reporting hub (preview, deploy, refresh)."""
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            embed=await build_report_hub_embed(interaction),
            view=MemberReportHubView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Engagement Report",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_mod_panel:engagement_report",
        emoji="📈",
        row=0,
    )
    async def engagement_report_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the activity ranking period selector."""
        if not await require_manage(interaction):
            return
        await interaction.response.send_message(
            embed=embed_builder.base_embed(
                title="Member activity ranking",
                description=(
                    "Select the activity period to analyse. Custom dates use the "
                    "configured report timezone, and the full ranked report is "
                    "published as a text file."
                ),
            ),
            view=EngagementRangeView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Engagement Contest",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_mod_panel:engagement_contest",
        emoji="🏆",
        row=0,
    )
    async def engagement_contest_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the engagement contest timeframe selector."""
        if not await require_manage(interaction):
            return
        await interaction.response.send_message(
            embed=build_contest_prompt_embed(),
            view=EngagementContestRangeView(),
            ephemeral=True,
        )

    # ── Row 1: messaging ──────────────────────────────────────
    @discord.ui.button(
        label="CGK Discord Announcement",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_mod_panel:announcements",
        emoji="📣",
        row=1,
    )
    async def announcements_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the weekly announcement hub (Monday through Friday posts)."""
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await open_announcements(interaction)

    @discord.ui.button(
        label="Embed Message",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_mod_panel:embed_message",
        emoji="📝",
        row=1,
    )
    async def embed_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the Embed Studio (composer plus the saved template library)."""
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await open_studio(interaction)

    @discord.ui.button(
        label="Normal Message",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_mod_panel:normal_message",
        emoji="💬",
        row=1,
    )
    async def normal_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the plain text message composer."""
        if not await require_manage(interaction):
            return
        await interaction.response.send_modal(PlainMessageModal())

    # ── Row 2: maintenance ────────────────────────────────────
    @discord.ui.button(
        label="Refresh Dashboard",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_mod_panel:refresh_dashboard",
        emoji="🔄",
        row=2,
    )
    async def refresh_dashboard_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Rebuilds the panel embed and re-applies the latest button set."""
        await interaction.response.defer()
        embed = await build_mod_panel_embed(
            bot=interaction.client, guild=interaction.guild
        )
        await interaction.edit_original_response(embed=embed, view=ModPanelView())
