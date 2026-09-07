"""
Mod Panel Cog for the CGK Linens Discord Bot.
Created by Aljay Leodones for CGK Linens.
"""

import discord
from discord import app_commands
from discord.ext import commands

from views.engagement_contest_view import (
    EngagementContestRangeView,
    build_contest_prompt_embed,
)
from views.member_report_view import MemberReportHubView, build_report_hub_embed
from views.mod_panel_view import ModPanelView, build_mod_panel_embed
from views.onboarding_view import OnboardingHubView, build_hub_embed


class ModPanelCog(commands.Cog):
    """Cog handling the management panel and administration commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="summon",
        description="Display the persistent CGK Linens management dashboard.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def summon_command(self, interaction: discord.Interaction):
        """Summons the persistent Mod Panel."""
        await interaction.response.defer()
        embed = await build_mod_panel_embed(bot=self.bot, guild=interaction.guild)
        await interaction.followup.send(embed=embed, view=ModPanelView())

    @app_commands.command(
        name="onboarding",
        description="Post the persistent member onboarding panel in this channel.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def onboarding_command(self, interaction: discord.Interaction):
        """Posts the standalone onboarding hub (also reachable from /summon)."""
        await interaction.response.defer()
        embed = await build_hub_embed(interaction)
        await interaction.followup.send(embed=embed, view=OnboardingHubView())

    @app_commands.command(
        name="community-report",
        description="Post the persistent community growth report panel here.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def community_report_command(self, interaction: discord.Interaction):
        """Posts the standalone reporting hub (also reachable from /summon)."""
        await interaction.response.defer()
        embed = await build_report_hub_embed(interaction)
        await interaction.followup.send(embed=embed, view=MemberReportHubView())

    @app_commands.command(
        name="engagement-contest",
        description="Launch and post the Engagement Contest Top 15 Leaderboard.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def engagement_contest_command(self, interaction: discord.Interaction):
        """Opens the Engagement Contest timeframe selector (also reachable from /summon)."""
        embed = build_contest_prompt_embed()
        await interaction.response.send_message(
            embed=embed, view=EngagementContestRangeView(), ephemeral=True
        )


async def setup(bot: commands.Bot):
    """Adds the ModPanelCog to the bot."""
    await bot.add_cog(ModPanelCog(bot))
