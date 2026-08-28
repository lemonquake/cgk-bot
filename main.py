"""
Main entry point for the CGK Linens Discord Bot.
Created by Aljay Leodones for CGK Linens.
"""

import asyncio
import logging
import sys
import discord
from discord.ext import commands

from config import DISCORD_TOKEN, GUILD_ID, BRAND_NAME
from views.mod_panel_view import ModPanelView

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cgk_bot")


class CGKBot(commands.Bot):
    """Custom Bot class for CGK Linens management."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        """Initializes persistent views, cogs, and slash command trees."""
        logger.info("Registering persistent views...")
        # Register the persistent ModPanelView so buttons work across restarts
        self.add_view(ModPanelView())

        logger.info("Loading extensions...")
        await self.load_extension("cogs.mod_panel")

        # Command synchronization
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info("Synced %d command(s) to test guild ID: %s", len(synced), GUILD_ID)
        else:
            synced = await self.tree.sync()
            logger.info("Synced %d global command(s).", len(synced))

    async def on_ready(self):
        """Triggered when the bot has connected to Discord."""
        logger.info("==========================================")
        logger.info("Logged in as: %s (ID: %s)", self.user.name, self.user.id)
        logger.info("Bot is active in %d server(s)", len(self.guilds))
        logger.info("==========================================")

        # Set bot presence status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{BRAND_NAME} Server",
        )
        await self.change_presence(
            status=discord.Status.online,
            activity=activity,
        )


def run():
    """Validates configuration and launches the bot."""
    if not DISCORD_TOKEN:
        logger.error(
            "DISCORD_TOKEN is missing! Please configure it in your .env file."
        )
        sys.exit(1)

    bot = CGKBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    run()
