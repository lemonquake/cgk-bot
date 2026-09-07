"""
Moderator interface for the CGK Linens onboarding system.
Created by Aljay Leodones for CGK Linens.

Flow:  Scan  ->  pick which join days  ->  compose  ->  choose delivery
       ->  pick the channel  ->  post + warm DM + onboarding log.
"""

from __future__ import annotations

import logging

import discord

from cogs.onboarding import CHANNEL_LABELS, DEFAULT_MESSAGE, DayGroup
from config import ONBOARDING_LOOKBACK_DAYS
from core.embed_script import PLACEHOLDER_HELP, resolve_text
from utils import embed_builder
from views.common import missing_cog, require_manage

logger = logging.getLogger("cgk_bot.onboarding_ui")

TEXT_CHANNEL_TYPES = [discord.ChannelType.text, discord.ChannelType.news]


def _onboarding_cog(interaction: discord.Interaction):
    return interaction.client.get_cog("OnboardingCog")


def _member_preview(members: list[discord.Member], limit: int = 12) -> str:
    names = [member.display_name for member in members[:limit]]
    extra = len(members) - len(names)
    preview = ", ".join(names) if names else "No members selected yet"
    return f"{preview} … and {extra} more" if extra > 0 else preview


# ── Step 4: pick the destination channel ───────────────────────────────────
class OnboardingChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, default_channel_id: int | None):
        super().__init__(
            placeholder="Choose the channel for the welcome post...",
            channel_types=TEXT_CHANNEL_TYPES,
            min_values=1,
            max_values=1,
        )
        self.default_channel_id = default_channel_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_manage(interaction):
            return
        parent: "OnboardingChannelSelectView" = self.view  # type: ignore[assignment]
        channel = interaction.guild.get_channel(self.values[0].id)
        if channel is None:
            await interaction.response.send_message(
                embed=embed_builder.error_embed(
                    "Channel unavailable", "That channel could not be opened."
                ),
                ephemeral=True,
            )
            return
        await parent.run(interaction, channel)


class OnboardingChannelSelectView(discord.ui.View):
    """Final confirmation step before the welcome post goes live."""

    def __init__(
        self,
        *,
        members: list[discord.Member],
        message: str,
        send_dm: bool,
        default_channel_id: int | None,
    ):
        super().__init__(timeout=600)
        self.members = members
        self.message = message
        self.send_dm = send_dm
        self.default_channel_id = default_channel_id
        self.add_item(OnboardingChannelSelect(default_channel_id))
        if default_channel_id is None:
            self.remove_item(self.use_saved_channel)

    @discord.ui.button(
        label="Use my saved welcome channel",
        style=discord.ButtonStyle.success,
        emoji="⭐",
        row=1,
    )
    async def use_saved_channel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        channel = interaction.guild.get_channel(self.default_channel_id or 0)
        if channel is None:
            await interaction.response.send_message(
                embed=embed_builder.warning_embed(
                    "Saved channel missing",
                    "Your saved welcome channel no longer exists. Pick one below, "
                    "or update it from **Onboarding → Channel Setup**.",
                ),
                ephemeral=True,
            )
            return
        await self.run(interaction, channel)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            embed=embed_builder.info_embed("Cancelled", "Nothing was sent."), view=None
        )
        self.stop()

    async def run(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | discord.Thread,
    ) -> None:
        await _execute_delivery(
            interaction,
            members=self.members,
            message=self.message,
            channel=channel,
            send_dm=self.send_dm,
        )
        self.stop()


# ── Step 3: choose how the welcome is delivered ────────────────────────────
class OnboardingDeliveryView(discord.ui.View):
    def __init__(self, *, members: list[discord.Member], message: str):
        super().__init__(timeout=600)
        self.members = members
        self.message = message

    async def _to_channel_step(
        self, interaction: discord.Interaction, *, send_dm: bool
    ) -> None:
        cog = _onboarding_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Onboarding")
            return
        channels = await cog.channel_ids(interaction.guild.id)
        embed = embed_builder.base_embed(
            title="Where should the welcome post go?",
            description=(
                f"{embed_builder.item(f'Members tagged: **{len(self.members)}**')}\n"
                f"{embed_builder.item('Warm DM: **' + ('yes' if send_dm else 'no') + '**')}\n"
                f"{embed_builder.SEPARATOR}\n"
                "Pick a channel below. Everyone selected is tagged in one post."
            ),
        )
        await interaction.response.edit_message(
            embed=embed,
            view=OnboardingChannelSelectView(
                members=self.members,
                message=self.message,
                send_dm=send_dm,
                default_channel_id=channels.get("welcome"),
            ),
        )
        self.stop()

    @discord.ui.button(
        label="Post publicly + warm DM",
        style=discord.ButtonStyle.success,
        emoji="📣",
        row=0,
    )
    async def post_and_dm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        await self._to_channel_step(interaction, send_dm=True)

    @discord.ui.button(
        label="Post publicly only", style=discord.ButtonStyle.primary, emoji="📢", row=0
    )
    async def post_only(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        await self._to_channel_step(interaction, send_dm=False)

    @discord.ui.button(
        label="Warm DM only", style=discord.ButtonStyle.secondary, emoji="✉️", row=1
    )
    async def dm_only(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        await _execute_delivery(
            interaction,
            members=self.members,
            message=self.message,
            channel=None,
            send_dm=True,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            embed=embed_builder.info_embed("Cancelled", "Nothing was sent."), view=None
        )
        self.stop()


# ── Step 2b: compose the message ───────────────────────────────────────────
class OnboardingComposerModal(discord.ui.Modal, title="Welcome Message"):
    def __init__(self, members: list[discord.Member], current_message: str):
        super().__init__(timeout=900)
        self.members = members
        self.message_input = discord.ui.TextInput(
            label="Welcome post",
            style=discord.TextStyle.paragraph,
            default=current_message[:1800],
            max_length=1800,
            required=True,
            placeholder="Placeholders: {onboarding_channel} {introductions_channel} {server_name}",
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await require_manage(interaction):
            return
        await _show_delivery_step(
            interaction, members=self.members, message=self.message_input.value
        )


async def _show_delivery_step(
    interaction: discord.Interaction,
    *,
    members: list[discord.Member],
    message: str,
) -> None:
    cog = _onboarding_cog(interaction)
    if cog is None:
        await missing_cog(interaction, "Onboarding")
        return
    channels = await cog.channel_ids(interaction.guild.id)
    preview = resolve_text(message, guild=interaction.guild, channels=channels) or ""

    embed = embed_builder.base_embed(
        title="Preview & delivery",
        description=(
            f"{embed_builder.section('Members selected')} **{len(members)}**\n"
            f"{_member_preview(members)}\n\n"
            f"{embed_builder.section('Public post preview')}\n"
            f"{preview[:1200]}\n"
            f"{embed_builder.SEPARATOR}\n"
            "Every member above is tagged in the post. The warm DM is a separate "
            "branded message with direct links to your onboarding channels."
        ),
    )
    await interaction.response.edit_message(
        embed=embed, view=OnboardingDeliveryView(members=members, message=message)
    )


# ── Step 2a: pick which join days to welcome ───────────────────────────────
class OnboardingDaySelect(discord.ui.Select):
    def __init__(self, groups: list[DayGroup]):
        total = sum(len(group.members) for group in groups)
        options = [
            discord.SelectOption(
                label=f"Everyone not yet welcomed ({total})",
                value="all",
                emoji="✅",
                description=f"All members from the last {ONBOARDING_LOOKBACK_DAYS} days",
            )
        ]
        for group in groups[:24]:
            options.append(
                discord.SelectOption(
                    label=f"{group.label} ({len(group.members)})",
                    value=group.key,
                    emoji="📅",
                    description=group.description[:100],
                )
            )
        super().__init__(
            placeholder="Select which days to welcome (you can pick several)...",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_manage(interaction):
            return
        parent: "OnboardingSelectionView" = self.view  # type: ignore[assignment]
        parent.apply_selection(set(self.values))
        await interaction.response.edit_message(
            embed=parent.build_embed(), view=parent
        )


class OnboardingSelectionView(discord.ui.View):
    """Day picker plus the two ways to continue (default text or custom text)."""

    def __init__(self, groups: list[DayGroup]):
        super().__init__(timeout=600)
        self.groups = groups
        self.selected_keys: set[str] = {"all"}
        self.add_item(OnboardingDaySelect(groups))

    # -- selection state ---------------------------------------
    def apply_selection(self, keys: set[str]) -> None:
        self.selected_keys = keys or {"all"}

    @property
    def selected_members(self) -> list[discord.Member]:
        if "all" in self.selected_keys:
            chosen = [member for group in self.groups for member in group.members]
        else:
            chosen = [
                member
                for group in self.groups
                if group.key in self.selected_keys
                for member in group.members
            ]
        unique: dict[int, discord.Member] = {member.id: member for member in chosen}
        return sorted(unique.values(), key=lambda m: m.joined_at, reverse=True)

    def build_embed(self) -> discord.Embed:
        members = self.selected_members
        breakdown = "\n".join(
            embed_builder.item(
                f"**{group.label}** — {len(group.members)} member(s)"
                + ("  ✅" if self._is_active(group.key) else "")
            )
            for group in self.groups
        )
        return embed_builder.base_embed(
            title="👋  New members waiting to be welcomed",
            description=(
                f"{embed_builder.section('Join days')}\n{breakdown}\n\n"
                f"{embed_builder.section('Currently selected')} "
                f"**{len(members)}** member(s)\n{_member_preview(members)}\n"
                f"{embed_builder.SEPARATOR}\n"
                "1. Choose the join days in the menu.\n"
                "2. Send the default welcome, or write your own first."
            ),
        )

    def _is_active(self, key: str) -> bool:
        return "all" in self.selected_keys or key in self.selected_keys

    # -- actions -----------------------------------------------
    async def _guard(self, interaction: discord.Interaction) -> list[discord.Member] | None:
        if not await require_manage(interaction):
            return None
        members = self.selected_members
        if not members:
            await interaction.response.send_message(
                embed=embed_builder.warning_embed(
                    "Nothing selected", "Pick at least one join day first."
                ),
                ephemeral=True,
            )
            return None
        return members

    @discord.ui.button(
        label="Send default welcome",
        style=discord.ButtonStyle.success,
        emoji="⚡",
        row=1,
    )
    async def use_default(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        members = await self._guard(interaction)
        if members is None:
            return
        await _show_delivery_step(interaction, members=members, message=DEFAULT_MESSAGE)
        self.stop()

    @discord.ui.button(
        label="Write my own message",
        style=discord.ButtonStyle.primary,
        emoji="✍️",
        row=1,
    )
    async def compose(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        members = await self._guard(interaction)
        if members is None:
            return
        await interaction.response.send_modal(
            OnboardingComposerModal(members, DEFAULT_MESSAGE)
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            embed=embed_builder.info_embed("Cancelled", "Nothing was sent."), view=None
        )
        self.stop()


# ── Delivery execution ─────────────────────────────────────────────────────
async def _execute_delivery(
    interaction: discord.Interaction,
    *,
    members: list[discord.Member],
    message: str,
    channel: discord.TextChannel | discord.Thread | None,
    send_dm: bool,
) -> None:
    cog = _onboarding_cog(interaction)
    if cog is None:
        await missing_cog(interaction, "Onboarding")
        return

    estimate = len(members) if send_dm else 0
    working = embed_builder.info_embed(
        "Sending the welcome...",
        (
            f"{embed_builder.item(f'Members: **{len(members)}**')}\n"
            + (
                embed_builder.item(
                    f"Warm DMs are paced at 1 per second (about {estimate}s)."
                )
                if send_dm
                else embed_builder.item("Public post only.")
            )
        ),
    )
    await interaction.response.edit_message(embed=working, view=None)

    try:
        result = await cog.deliver(
            guild=interaction.guild,
            members=members,
            message=message,
            moderator=interaction.user,
            channel=channel,
            send_dm=send_dm,
        )
    except discord.Forbidden:
        await interaction.edit_original_response(
            embed=embed_builder.error_embed(
                "Missing permissions",
                "The bot cannot post in that channel. Grant it **Send Messages** "
                "and **Embed Links**, then try again.",
            ),
            view=None,
        )
        return
    except discord.HTTPException as exc:
        logger.exception("Onboarding delivery failed")
        await interaction.edit_original_response(
            embed=embed_builder.error_embed("Delivery failed", str(exc)), view=None
        )
        return

    lines = [
        embed_builder.item(f"Members welcomed: **{result.marked}**"),
        embed_builder.item(
            f"Public post: {result.posted_channel.mention}"
            if result.posted_channel
            else "Public post: *skipped*"
        ),
    ]
    if send_dm:
        lines.append(
            embed_builder.item(
                f"Warm DMs delivered: **{result.dm_success}** · "
                f"blocked/closed DMs: **{result.dm_failed}**"
            )
        )
        if result.failed_names:
            lines.append(
                embed_builder.item(
                    "Could not DM: " + ", ".join(result.failed_names)
                )
            )
    lines.append(
        embed_builder.item(
            "These members are now logged as onboarded and will not appear in the "
            "next scan."
        )
    )

    try:
        await interaction.edit_original_response(
            embed=embed_builder.success_embed("Welcome sent", "\n".join(lines)),
            view=None,
        )
    except discord.HTTPException:
        # Very large DM batches can outlive the interaction token; the welcome
        # itself already went out, so this summary is best-effort.
        logger.info("Welcome finished after the interaction token expired.")


# ── Channel setup ──────────────────────────────────────────────────────────
class OnboardingChannelSetting(discord.ui.ChannelSelect):
    def __init__(self, key: str, row: int, current_name: str | None):
        current = f" -> #{current_name}" if current_name else " -> not set"
        super().__init__(
            placeholder=f"{CHANNEL_LABELS[key]}{current}"[:150],
            channel_types=TEXT_CHANNEL_TYPES,
            min_values=1,
            max_values=1,
            row=row,
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await require_manage(interaction):
            return
        cog = _onboarding_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Onboarding")
            return
        await cog.set_channel(interaction.guild.id, self.key, self.values[0].id)
        channels = await cog.channel_ids(interaction.guild.id)
        # Rebuild the menus so each one shows the channel it now points at.
        await interaction.response.edit_message(
            embed=await build_settings_embed(interaction),
            view=OnboardingSettingsView(channels, interaction.guild),
        )


async def build_settings_embed(interaction: discord.Interaction) -> discord.Embed:
    cog = _onboarding_cog(interaction)
    channels = await cog.channel_ids(interaction.guild.id) if cog else {}
    lines = []
    for key, label in CHANNEL_LABELS.items():
        channel_id = channels.get(key)
        value = f"<#{channel_id}>" if channel_id else "*not set*"
        lines.append(embed_builder.item(f"**{label}:** {value}"))
    return embed_builder.base_embed(
        title="⚙️  Onboarding channel setup",
        description=(
            f"{embed_builder.section('Current channels')}\n" + "\n".join(lines) + "\n\n"
            f"{embed_builder.SEPARATOR}\n"
            "Pick a channel in any menu below to change it — it saves instantly and "
            "survives restarts.\n\n"
            f"{embed_builder.section('Placeholders you can use in messages')}\n"
            f"`{PLACEHOLDER_HELP}`"
        ),
    )


class OnboardingSettingsView(discord.ui.View):
    def __init__(self, channels: dict[str, int | None], guild: discord.Guild):
        super().__init__(timeout=600)
        for row, key in enumerate(CHANNEL_LABELS):
            channel = guild.get_channel(channels.get(key) or 0)
            self.add_item(
                OnboardingChannelSetting(key, row, channel.name if channel else None)
            )

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, emoji="✅", row=3)
    async def done(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            embed=embed_builder.success_embed(
                "Channel setup saved", "Your onboarding channels are ready to use."
            ),
            view=None,
        )
        self.stop()


# ── Reset confirmation ─────────────────────────────────────────────────────
class OnboardingResetView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(
        label="Yes, clear the onboarding log",
        style=discord.ButtonStyle.danger,
        emoji="♻️",
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        cog = _onboarding_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Onboarding")
            return
        cleared = await cog.clear_onboarded(interaction.guild.id)
        await interaction.response.edit_message(
            embed=embed_builder.success_embed(
                "Onboarding log cleared",
                embed_builder.item(f"Removed **{cleared}** logged member(s).")
                + "\nEveryone who joined recently can be welcomed again.",
            ),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            embed=embed_builder.info_embed("Cancelled", "The log was left untouched."),
            view=None,
        )
        self.stop()


# ── Persistent onboarding hub ──────────────────────────────────────────────
async def build_hub_embed(interaction: discord.Interaction) -> discord.Embed:
    cog = _onboarding_cog(interaction)
    if cog is None:
        return embed_builder.error_embed(
            "Onboarding unavailable", "The onboarding module did not load."
        )
    stats = await cog.onboarding_stats(interaction.guild)
    channels = await cog.channel_ids(interaction.guild.id)
    configured = sum(1 for value in channels.values() if value)

    status_lines = [
        embed_builder.item("Waiting to be welcomed: **{}**".format(stats["pending"])),
        embed_builder.item(
            "Welcomed in the last 7 days: **{}**".format(stats["last_7_days"])
        ),
        embed_builder.item("Welcomed all-time: **{}**".format(stats["total"])),
        embed_builder.item("Channels configured: **{}/3**".format(configured)),
    ]
    how_lines = [
        embed_builder.item(
            "**Scan** - find everyone who joined in the last "
            "{} days and was never welcomed.".format(ONBOARDING_LOOKBACK_DAYS)
        ),
        embed_builder.item("Pick **which join days** to include, then send."),
        embed_builder.item(
            "**Channel setup** - choose where posts and DM links point."
        ),
    ]

    intro = (
        f"Welcome new members to **{interaction.guild.name}** with a tagged public "
        "post and a warm, branded DM — then keep a log so nobody is welcomed twice."
    )
    blocks = [
        intro,
        embed_builder.SEPARATOR,
        embed_builder.section("Right now"),
        "\n".join(status_lines),
        "",
        embed_builder.section("How to use it"),
        "\n".join(how_lines),
    ]
    return embed_builder.base_embed(
        title="👋  Member Onboarding",
        description="\n".join(blocks),
    )


class OnboardingHubView(discord.ui.View):
    """Persistent onboarding hub (static custom_ids, survives restarts)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Scan for new members",
        style=discord.ButtonStyle.success,
        custom_id="cgk_onboarding:scan",
        emoji="🔍",
        row=0,
    )
    async def scan(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        cog = _onboarding_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Onboarding")
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        pending = await cog.pending_members(interaction.guild)
        if not pending:
            await interaction.followup.send(
                embed=embed_builder.success_embed(
                    "Everyone is welcomed",
                    f"No member who joined in the last {ONBOARDING_LOOKBACK_DAYS} "
                    "days is waiting for a welcome.",
                ),
                ephemeral=True,
            )
            return

        view = OnboardingSelectionView(cog.group_by_day(pending))
        await interaction.followup.send(
            embed=view.build_embed(), view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Channel setup",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_onboarding:setup",
        emoji="⚙️",
        row=0,
    )
    async def setup_channels(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        cog = _onboarding_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Onboarding")
            return
        channels = await cog.channel_ids(interaction.guild.id)
        await interaction.response.send_message(
            embed=await build_settings_embed(interaction),
            view=OnboardingSettingsView(channels, interaction.guild),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Onboarding stats",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_onboarding:stats",
        emoji="📋",
        row=1,
    )
    async def stats(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            embed=await build_hub_embed(interaction), ephemeral=True
        )

    @discord.ui.button(
        label="Reset onboarding log",
        style=discord.ButtonStyle.danger,
        custom_id="cgk_onboarding:reset",
        emoji="♻️",
        row=1,
    )
    async def reset(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await require_manage(interaction):
            return
        await interaction.response.send_message(
            embed=embed_builder.warning_embed(
                "Clear the onboarding log?",
                "Every member who joined recently becomes selectable again, so they "
                "can receive a second welcome. This cannot be undone.",
            ),
            view=OnboardingResetView(),
            ephemeral=True,
        )
