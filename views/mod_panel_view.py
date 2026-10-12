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
from views.cgk_onboarding_view import CGKOnboardingHubView, build_cgk_hub_embed
from views.common import require_manage
from views.creator_onboarding_view import (
    CreatorOnboardingHubView,
    build_creator_hub_embed,
)
from views.embed_studio_view import open_studio
from views.engagement_contest_view import (
    EngagementContestHubView,
    build_contest_hub_embed,
)
from views.engagement_report_view import EngagementRangeView
from views.member_report_view import MemberReportHubView, build_report_hub_embed
from views.onboarding_view import (
    OnboardingHubView,
    build_hub_embed,
    open_questionnaire_poster,
)
from views.plain_message_view import PlainMessageModal

logger = logging.getLogger("cgk_bot.mod_panel_ui")

FIELD_LIMIT = 1024

FUNCTION_GUIDE = [
    ("🎟️ CGK Onboarding", "Scan new members and open a private #handle-onboarding channel for each — finishing it unlocks the server. 🧪 Test it on yourself (or /test-onboarding); 🔒 Close onboarding deletes a channel."),
    ("👋 Onboarding", "Open a private channel for each new member and tag them there with the TikTok Shop creator question (✅ YES / ❌ NO). 🧪 Test it in any channel."),
    ("ℹ️ Information Onboarding", "Welcome new members with a tagged post and warm DM, plus the member questionnaire."),
    ("📊 Community Reports", "Growth reports that refresh themselves in a channel."),
    ("📈 Engagement Report", "Rank members by messages, reactions and threads."),
    ("🏆 Engagement Contest", "Start a contest, publish the Top 15 leaderboard, end it, or review past contests."),
    ("📣 CGK Discord Announcement", "The four weekly posts — edit, publish or schedule them."),
    ("📝 Embed Message", "Compose, save and reuse branded embeds — templates included."),
    ("💬 Normal Message", "Write a plain message, preview it, edit it, attach images, then post."),
    ("📋 Post Questionnaire", "Post the member questionnaire (Start onboarding) in any channel, as many times as you like."),
    ("🔄 Refresh Dashboard", "Reload this panel with the latest data and buttons."),
]


async def build_mod_panel_embed(
    bot: discord.Client, guild: discord.Guild | None = None
) -> discord.Embed:
    """Builds the Mod Panel embed with live server, module and health data."""
    latency_ms = round(bot.latency * 1000) if bot.latency else 0
    onboarding_cog = bot.get_cog("OnboardingCog")
    creator_cog = bot.get_cog("CreatorOnboardingCog")
    cgk_cog = bot.get_cog("CGKOnboardingCog")
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

    if guild is not None and cgk_cog is not None:
        try:
            cgk_stats = await cgk_cog.stats(guild)
            embed.add_field(
                name=embed_builder.section("CGK onboarding"),
                value="\n".join(
                    [
                        embed_builder.item(f"Waiting to be tagged: **{cgk_stats['pending']}**"),
                        embed_builder.item(
                            f"Open onboarding channels: **{cgk_stats['channels']}** · "
                            f"finished: **{cgk_stats['completed']}**"
                        ),
                    ]
                ),
                inline=False,
            )
        except RuntimeError:
            logger.warning("CGK onboarding statistics were not ready for the panel")

    if guild is not None and creator_cog is not None:
        try:
            creator_stats = await creator_cog.stats(guild)
            embed.add_field(
                name=embed_builder.section("Onboarding"),
                value="\n".join(
                    [
                        embed_builder.item(
                            f"Waiting for the creator welcome: **{creator_stats['pending']}**"
                        ),
                        embed_builder.item(
                            f"Answered ✅ **{creator_stats['yes']}** · ❌ **{creator_stats['no']}**"
                        ),
                    ]
                ),
                inline=False,
            )
        except RuntimeError:
            logger.warning("Creator onboarding statistics were not ready for the panel")

    if guild is not None and onboarding_cog is not None:
        try:
            stats = await onboarding_cog.onboarding_stats(guild)
            pending = stats["pending"]
            welcomed = stats["total"]
            embed.add_field(
                name=embed_builder.section("Information onboarding"),
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

    if guild is not None and contest_cog is not None:
        try:
            active_contest = await contest_cog.get_active_contest(guild.id)
        except RuntimeError:
            logger.warning("Contest status was not ready for the panel")
        else:
            if active_contest is None:
                contest_summary = embed_builder.item(
                    "No contest running — open **Engagement Contest** to start one."
                )
            else:
                contest_summary = "\n".join(
                    [
                        embed_builder.item(
                            f"**{active_contest.name}** — running for "
                            f"**{active_contest.describe_duration()}**"
                        ),
                        embed_builder.item(
                            f"Opened by **{active_contest.started_by_name or 'a moderator'}**"
                        ),
                    ]
                )
            embed.add_field(
                name=embed_builder.section("Engagement contest"),
                value=contest_summary,
                inline=False,
            )

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

    # A field holds at most 1024 characters, so the guide spills into more.
    guide = [
        embed_builder.item(f"**{label}** — {description}")
        for label, description in FUNCTION_GUIDE
    ]
    chunks: list[list[str]] = [[]]
    for line in guide:
        if chunks[-1] and len("\n".join(chunks[-1] + [line])) > FIELD_LIMIT:
            chunks.append([])
        chunks[-1].append(line)
    for index, chunk in enumerate(chunks):
        embed.add_field(
            name=embed_builder.section("What each button does") if index == 0 else "\u200b",
            value="\n".join(chunk),
            inline=False,
        )

    embed.add_field(
        name=embed_builder.section("System health"),
        value=embed_builder.status_block(
            {
                "CGK onboarding": "ready" if cgk_cog else "unavailable",
                "Onboarding module": "ready" if creator_cog else "unavailable",
                "Information onboarding": "ready" if onboarding_cog else "unavailable",
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

    # ── Row 0: onboarding ─────────────────────────────────────
    @discord.ui.button(
        label="CGK Onboarding",
        style=discord.ButtonStyle.success,
        custom_id="cgk_mod_panel:cgk_onboarding",
        emoji="🎟️",
        row=0,
    )
    async def cgk_onboarding_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the CGK Onboarding hub (private per-member channels)."""
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            embed=await build_cgk_hub_embed(interaction),
            view=CGKOnboardingHubView(),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Onboarding",
        style=discord.ButtonStyle.success,
        custom_id="cgk_mod_panel:creator_onboarding",
        emoji="👋",
        row=0,
    )
    async def creator_onboarding_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the creator onboarding hub (scan, test, settings)."""
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            embed=await build_creator_hub_embed(interaction),
            view=CreatorOnboardingHubView(),
            ephemeral=True,
        )

    # The custom_id stays "onboarding" so panels posted before the rename
    # keep working.
    @discord.ui.button(
        label="Information Onboarding",
        style=discord.ButtonStyle.success,
        custom_id="cgk_mod_panel:onboarding",
        emoji="ℹ️",
        row=0,
    )
    async def onboarding_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Publishes the member form and opens the moderator onboarding hub."""
        from cogs.questionnaire import publish_questionnaire

        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        notice = await publish_questionnaire(interaction)
        await interaction.followup.send(
            content=notice,
            embed=await build_hub_embed(interaction),
            view=OnboardingHubView(),
            ephemeral=True,
        )

    # ── Row 1: reports ────────────────────────────────────────
    @discord.ui.button(
        label="Community Reports",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_mod_panel:community_report",
        emoji="📊",
        row=1,
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
        row=1,
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
        row=1,
    )
    async def engagement_contest_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the engagement contest hub (start, publish, end, history)."""
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            embed=await build_contest_hub_embed(interaction),
            view=EngagementContestHubView(),
            ephemeral=True,
        )

    # ── Row 2: messaging (Post Questionnaire joins row 0) ─────
    @discord.ui.button(
        label="CGK Discord Announcement",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_mod_panel:announcements",
        emoji="📣",
        row=2,
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
        row=2,
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
        row=2,
    )
    async def normal_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Opens the plain message composer (preview, edit and images)."""
        if not await require_manage(interaction):
            return
        await interaction.response.send_modal(PlainMessageModal())

    @discord.ui.button(
        label="Post Questionnaire",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_mod_panel:post_questionnaire",
        emoji="📋",
        row=0,
    )
    async def post_questionnaire_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Pick any channel and post the member questionnaire there."""
        if not await require_manage(interaction):
            return
        await open_questionnaire_poster(interaction)

    # ── Row 3: maintenance ────────────────────────────────────
    @discord.ui.button(
        label="Refresh Dashboard",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_mod_panel:refresh_dashboard",
        emoji="🔄",
        row=3,
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
