"""
Mod Panel Cog for the CGK Linens Discord Bot.
Created by Aljay Leodones for CGK Linens.
"""

import discord
from discord import app_commands
from discord.ext import commands
from views.mod_panel_view import ModPanelView, build_mod_panel_embed


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
        embed = build_mod_panel_embed(
            bot=self.bot,
            guild=interaction.guild,
        )
        view = ModPanelView()
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    """Adds the ModPanelCog to the bot."""
    await bot.add_cog(ModPanelCog(bot))
