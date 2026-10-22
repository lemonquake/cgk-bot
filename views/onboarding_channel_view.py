"""Public onboarding entry point and the moderator Auto Onboarding switch."""

import logging

import discord

from cogs.cgk_onboarding import AUTO_HIDDEN_CHANNEL_ID, AUTO_ONBOARDING_ROLE_ID, CategoryFull
from config import BRAND_NAME
from utils import embed_builder
from views.common import missing_cog, require_manage
from views.creator_onboarding_view import OnboardingTicketView

logger = logging.getLogger(__name__)


def onboarding_channel_embed() -> discord.Embed:
    return embed_builder.base_embed(
        title=f"Welcome to {BRAND_NAME}",
        description=(
            "**Complete onboarding to get full access to the server.**\n\n"
            "Click **START MY ONBOARDING** below to open your private onboarding "
            "channel. Follow the questions, read the community rules, and submit "
            "your member information.\n\n"
            "Once your information is saved, the bot will give you the server's "
            "access role and remove your **Onboarding** role. Your answers stay "
            "private and are shared only with our team.\n\n"
            "If you have already started, the button takes you back to your "
            "existing onboarding channel."
        ),
    )


class OnboardingStartView(discord.ui.View):
    """Every posted entry button remains usable after bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="START MY ONBOARDING",
        style=discord.ButtonStyle.success,
        custom_id="cgk_onboarding_channel:start",
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or interaction.user.bot:
            await interaction.response.send_message(
                "Please start onboarding from the server.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog = interaction.client.get_cog("CGKOnboardingCog")
        if cog is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        try:
            settings = await cog.settings(interaction.guild.id)
            problems = cog.setup_problems(interaction.guild, settings)
            if problems:
                logger.warning("Cannot start onboarding in %s: %s", interaction.guild.id, problems)
                await interaction.followup.send(
                    "Onboarding is not ready yet. Please contact a moderator so "
                    "they can check the onboarding settings and bot permissions.",
                    ephemeral=True,
                )
                return
            category = cog.category(interaction.guild, settings)
            channel, created = await cog.start_self_service(
                interaction.user, category, OnboardingTicketView()
            )
        except CategoryFull:
            await interaction.followup.send(
                "The onboarding category is full. Please contact a moderator "
                "so they can make room for your onboarding channel.",
                ephemeral=True,
            )
            return
        except Exception:
            logger.exception("Could not start onboarding for %s", interaction.user.id)
            await interaction.followup.send(
                "Your onboarding channel could not be opened. Please try again "
                "or contact a moderator.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"{'Your private onboarding channel is ready' if created else 'Continue your onboarding'}: "
            f"{channel.mention}. Follow the steps there to get full server access.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


def auto_onboarding_embed(enabled: bool, problems: list[str] | None = None) -> discord.Embed:
    state = "🟢 **ON**" if enabled else "🔴 **OFF**"
    description = (
        f"Auto onboarding is {state}.\n\n"
        "While it is ON, every member who joins automatically gets the "
        f"<@&{AUTO_ONBOARDING_ROLE_ID}> role, loses sight of <#{AUTO_HIDDEN_CHANNEL_ID}>, "
        "and gets their own private onboarding channel. When they finish, they "
        "get the access role, the onboarding roles are removed and the hidden "
        "channel comes back.\n\n"
        "While it is OFF, nothing happens when members join."
    )
    if enabled and problems:
        description += "\n\n⚠️ **Fix these, or new members won't be onboarded properly:**\n"
        description += "\n".join(f"• {problem}" for problem in problems)
    return embed_builder.base_embed(title="Auto Onboarding", description=description)


class AutoOnboardingView(discord.ui.View):
    """A private moderator switch; turning it ON or OFF takes effect at once."""

    def __init__(self, enabled: bool):
        super().__init__(timeout=300)
        self.turn_on.disabled = enabled
        self.turn_off.disabled = not enabled

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage(interaction)

    async def _apply(self, interaction: discord.Interaction, enabled: bool) -> None:
        cog = interaction.client.get_cog("CGKOnboardingCog")
        if cog is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        await cog.set_auto_enabled(interaction.guild.id, enabled)
        logger.info(
            "Auto onboarding turned %s in %s by %s",
            "on" if enabled else "off", interaction.guild.id, interaction.user.id,
        )
        problems = cog.auto_problems(interaction.guild, await cog.settings(interaction.guild.id))
        await interaction.response.edit_message(
            embed=auto_onboarding_embed(enabled, problems), view=AutoOnboardingView(enabled)
        )

    @discord.ui.button(label="Turn ON", style=discord.ButtonStyle.success, emoji="🟢")
    async def turn_on(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply(interaction, True)

    @discord.ui.button(label="Turn OFF", style=discord.ButtonStyle.danger, emoji="🔴")
    async def turn_off(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._apply(interaction, False)


async def open_auto_onboarding_toggle(interaction: discord.Interaction):
    if not await require_manage(interaction):
        return
    cog = interaction.client.get_cog("CGKOnboardingCog")
    if cog is None:
        await missing_cog(interaction, "CGK Onboarding")
        return
    enabled = await cog.auto_enabled(interaction.guild.id)
    problems = cog.auto_problems(interaction.guild, await cog.settings(interaction.guild.id))
    await interaction.response.send_message(
        embed=auto_onboarding_embed(enabled, problems),
        view=AutoOnboardingView(enabled),
        ephemeral=True,
    )
