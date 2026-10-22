"""Public onboarding entry point and moderator channel picker."""

import logging

import discord

from cogs.cgk_onboarding import CategoryFull
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


class OnboardingChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Choose the channel for the onboarding button",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.channel_id = self.values[0].id
        view.post.disabled = False
        await interaction.response.edit_message(
            content=f"Selected <#{view.channel_id}>. Click **Post onboarding button** to publish.",
            view=view,
        )


class OnboardingChannelView(discord.ui.View):
    """A private moderator picker; publishing requires an explicit click."""

    def __init__(self):
        super().__init__(timeout=300)
        self.channel_id = None
        self.add_item(OnboardingChannelSelect())
        self.post.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage(interaction)

    @discord.ui.button(
        label="Post onboarding button", style=discord.ButtonStyle.success, row=1
    )
    async def post(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(
                "That channel could not be found. Please select a text channel.",
                ephemeral=True,
            )
            return
        permissions = channel.permissions_for(interaction.guild.me)
        if not all(
            getattr(permissions, name, False)
            for name in ("view_channel", "send_messages", "embed_links")
        ):
            await interaction.followup.send(
                f"The bot needs **View Channel**, **Send Messages**, and **Embed Links** "
                f"in {channel.mention}.",
                ephemeral=True,
            )
            return
        try:
            message = await channel.send(
                embed=onboarding_channel_embed(),
                view=OnboardingStartView(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception("Could not post the onboarding button in %s", channel.id)
            await interaction.followup.send(
                "Discord could not post the onboarding button. Check the bot's "
                "channel permissions and try again.",
                ephemeral=True,
            )
            return
        await interaction.edit_original_response(
            content=f"Onboarding button posted in {channel.mention}. [View message]({message.jump_url})",
            view=None,
        )
        self.stop()


async def open_onboarding_channel_picker(interaction: discord.Interaction):
    if not await require_manage(interaction):
        return
    await interaction.response.send_message(
        content=(
            "Select a channel, then click **Post onboarding button**. Members can "
            "use **START MY ONBOARDING** there to begin the full onboarding flow."
        ),
        view=OnboardingChannelView(),
        ephemeral=True,
    )
