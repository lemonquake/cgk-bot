"""
Persistent Mod Panel View for the CGK Linens Discord Bot.
Created by Aljay Leodones for CGK Linens.
"""

from datetime import datetime, timezone
import discord
from config import BRAND_COLOR, EMBED_FOOTER_TEXT


def build_mod_panel_embed(bot: discord.Client, guild: discord.Guild = None) -> discord.Embed:
    """
    Constructs the Mod Panel embed displaying current bot status and available actions.
    """
    latency_ms = round(bot.latency * 1000) if bot.latency else 0
    guild_name = guild.name if guild else "Unknown Server"
    member_count = guild.member_count if guild else "N/A"

    embed = discord.Embed(
        title="CGK Linens — Management Panel",
        description=(
            "Welcome to the CGK Linens bot control panel. "
            "Use the buttons below to manage server communications and view system status."
        ),
        color=BRAND_COLOR,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(
        name="Server Information",
        value=f"• **Server:** {guild_name}\n• **Total Members:** {member_count}",
        inline=True,
    )

    embed.add_field(
        name="Bot Status",
        value=f"• **Status:** Online\n• **Latency:** {latency_ms}ms",
        inline=True,
    )

    embed.add_field(
        name="Available Functions",
        value=(
            "• **Embed Message:** Create and publish rich embed announcements.\n"
            "• **Normal Message:** Send plain text messages through the bot.\n"
            "• **Refresh Dashboard:** Reload the panel with the latest data and features."
        ),
        inline=False,
    )

    embed.set_footer(text=EMBED_FOOTER_TEXT)
    return embed


class ModPanelView(discord.ui.View):
    """
    Persistent view for the moderator dashboard.
    timeout=None and static custom_ids ensure the view stays active across restarts.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Embed Message",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_mod_panel:embed_message",
        emoji="📝",
    )
    async def embed_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Placeholder action for the Embed Message builder."""
        await interaction.response.send_message(
            "The Embed Message tool is currently being configured and will be available soon.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Normal Message",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_mod_panel:normal_message",
        emoji="💬",
    )
    async def normal_message_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Placeholder action for the Normal Message sender."""
        await interaction.response.send_message(
            "The Normal Message tool is currently being configured and will be available soon.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Refresh Dashboard",
        style=discord.ButtonStyle.success,
        custom_id="cgk_mod_panel:refresh_dashboard",
        emoji="🔄",
    )
    async def refresh_dashboard_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Refreshes the mod panel embed with updated server and bot information."""
        updated_embed = build_mod_panel_embed(
            bot=interaction.client,
            guild=interaction.guild,
        )
        await interaction.response.edit_message(embed=updated_embed, view=self)
        await interaction.followup.send(
            "Dashboard refreshed successfully with the latest data.",
            ephemeral=True,
        )
