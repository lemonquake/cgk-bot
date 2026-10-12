"""
Interfaces for creator onboarding (the TikTok Shop question).
Created by Aljay Leodones for CGK Linens.

Member flow, shared by the public "Onboarding" post and every private
CGK Onboarding channel:

    ❌ NO   ->  "how to get started on TikTok Shop" guide
    ✅ YES  ->  "where are you in your TikTok Shop journey?"
                  🌱 Still learning  ->  pointer to #🛍️tiktok-shop-101,
                                         then ✅ I've finished TikTok Shop 101
                  🔥 Experienced     ->  community rules + questionnaire
    Questionnaire submitted  ->  answers saved and queued for Slack,
                                 access role granted

In a shared channel every reply is ephemeral (only the member who clicked
sees it). Inside a member's own CGK Onboarding channel the replies are normal
messages, so the conversation stays in their channel - and only that member
can answer there. Every button has a static custom_id, so posts keep working
after a restart.

Moderator side mirrors Information Onboarding: Scan -> pick the join days
and the channel -> Send. **🧪 Test message** posts the interactive message to
any channel without tagging or logging anyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

import discord

from cogs.creator_onboarding import (
    CHANNEL_HINTS,
    CHANNEL_LABELS,
    FINISHED_101_LABEL,
    GETTING_STARTED_NAME,
    JOURNEY_QUESTION,
    NEXT_STEP_MESSAGE,
    NOT_A_CREATOR_MESSAGE,
    WELCOME_MESSAGE,
    CreatorSettings,
    completion_message,
    learning_message,
)
from cogs.onboarding import DayGroup, missing_permissions
from config import ONBOARDING_LOOKBACK_DAYS
from utils import embed_builder
from views.common import ack, missing_cog, replace_message, require_manage
from views.questionnaire_view import QuestionnaireModal, questionnaire_embed

logger = logging.getLogger("cgk_bot.creator_onboarding_ui")

TEXT_CHANNEL_TYPES = [discord.ChannelType.text, discord.ChannelType.news]
COMPOSER_TIMEOUT = 900
NOTICE_STYLES = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}
SOURCE_LABELS = {"saved": "", "env": " *(from .env)*", "unset": ""}

LEARNING_LABEL = "Still learning the ropes (requesting samples, filming, editing, etc.)"
EXPERIENCED_LABEL = "Experienced and ready to create"
NO_MENTIONS = discord.AllowedMentions.none()


def _creator_cog(interaction: discord.Interaction):
    return interaction.client.get_cog("CreatorOnboardingCog")


def _cgk_cog(interaction: discord.Interaction):
    return interaction.client.get_cog("CGKOnboardingCog")


def _channel_line(channel_id: int | None, source: str = "saved") -> str:
    if not channel_id:
        return "*not set*"
    return f"<#{channel_id}>{SOURCE_LABELS.get(source, '')}"


def _getting_started_line(settings: CreatorSettings) -> str:
    channel_id = settings.channels.get("getting_started")
    if channel_id:
        return _channel_line(channel_id, settings.sources["getting_started"])
    return f"*not set — uses the channel named #{GETTING_STARTED_NAME}*"


async def _record(interaction: discord.Interaction, **answer) -> None:
    """Saves an answer after the reply went out; never fails the click."""
    cog = _creator_cog(interaction)
    if cog is None or interaction.guild is None:
        return
    try:
        await cog.record_answer(interaction.guild.id, interaction.user.id, **answer)
    except Exception:  # noqa: BLE001 - stats only, the member already has the reply
        logger.warning("Could not record a creator onboarding answer", exc_info=True)


async def ticket_owner(interaction: discord.Interaction) -> int | None:
    """The member whose CGK Onboarding channel this click happened in, if any."""
    cog = _cgk_cog(interaction)
    if cog is None or interaction.guild is None:
        return None
    try:
        return await cog.owner_of(interaction.channel)
    except Exception:  # noqa: BLE001 - treat it as a shared channel
        logger.warning("Could not look up a CGK onboarding channel", exc_info=True)
        return None


async def _not_yours(interaction: discord.Interaction, owner: int) -> None:
    await interaction.response.send_message(
        f"This onboarding belongs to <@{owner}> — only they can answer here.",
        ephemeral=True,
        allowed_mentions=NO_MENTIONS,
    )


async def _respond(
    interaction: discord.Interaction,
    content: str,
    *,
    view: discord.ui.View | None = None,
    embed: discord.Embed | None = None,
    suppress_embeds: bool = False,
) -> bool:
    """
    Answers a member's click.

    A normal message inside the member's own onboarding channel, ephemeral
    anywhere else. Returns False when the channel belongs to someone else.
    """
    owner = await ticket_owner(interaction)
    if owner is not None and owner != interaction.user.id:
        await _not_yours(interaction, owner)
        return False
    extra: dict = {}
    if view is not None:
        extra["view"] = view
    if embed is not None:
        extra["embed"] = embed
    await interaction.response.send_message(
        content,
        ephemeral=owner is None,
        suppress_embeds=suppress_embeds,
        allowed_mentions=NO_MENTIONS,
        **extra,
    )
    return True


async def _send_next_step(interaction: discord.Interaction) -> bool:
    """Community rules with the Slack-connected questionnaire right below."""
    return await _respond(
        interaction,
        NEXT_STEP_MESSAGE,
        embed=questionnaire_embed(),
        view=CreatorQuestionnaireView(),
    )


# ── Member-facing persistent views ─────────────────────────────────────────
class CreatorWelcomeView(discord.ui.View):
    """✅ YES / ❌ NO under the welcome post."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="YES",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="cgk_creator_onboarding:yes",
    )
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await _respond(interaction, JOURNEY_QUESTION, view=CreatorJourneyView()):
            await _record(interaction, is_creator=True)

    @discord.ui.button(
        label="NO",
        style=discord.ButtonStyle.secondary,
        emoji="❌",
        custom_id="cgk_creator_onboarding:no",
    )
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await _respond(interaction, NOT_A_CREATOR_MESSAGE, suppress_embeds=True):
            await _record(interaction, is_creator=False)


class CreatorJourneyView(discord.ui.View):
    """🌱 / 🔥 on the follow-up a ✅ YES opens."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label=LEARNING_LABEL,
        style=discord.ButtonStyle.primary,
        emoji="🌱",
        custom_id="cgk_creator_onboarding:learning",
    )
    async def learning(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel_id = None
        cog = _creator_cog(interaction)
        if cog is not None and interaction.guild is not None:
            try:
                channel_id = (await cog.settings(interaction.guild.id)).channels.get(
                    "getting_started"
                )
            except Exception:  # noqa: BLE001 - fall back to the channel name
                logger.warning("Could not read the getting-started channel", exc_info=True)
        if await _respond(
            interaction, learning_message(interaction.guild, channel_id), view=Shop101DoneView()
        ):
            await _record(interaction, is_creator=True, journey="learning")

    @discord.ui.button(
        label=EXPERIENCED_LABEL,
        style=discord.ButtonStyle.primary,
        emoji="🔥",
        custom_id="cgk_creator_onboarding:experienced",
    )
    async def experienced(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if await _send_next_step(interaction):
            await _record(interaction, is_creator=True, journey="experienced")


class Shop101DoneView(discord.ui.View):
    """Under the 🌱 reply, and on the checkpoint posted in TikTok Shop 101."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label=FINISHED_101_LABEL,
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="cgk_creator_onboarding:finished_101",
    )
    async def finished(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _send_next_step(interaction)


class CreatorQuestionnaireModal(QuestionnaireModal):
    """The member questionnaire; finishing it also grants the access role."""

    def __init__(self, user, defaults=None, *, in_ticket: bool = False):
        super().__init__(user, defaults)
        self.in_ticket = in_ticket

    def reopen(self, user, answers):
        return type(self)(user, answers, in_ticket=self.in_ticket)

    async def after_save(self, interaction: discord.Interaction, saved: bool) -> None:
        """Grants the access role, then sends the "full access" message."""
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        cog = _cgk_cog(interaction)
        granted = False
        if cog is not None and member is not None:
            try:
                granted = await cog.complete(member)
            except Exception:  # noqa: BLE001 - the answers are already safe
                logger.warning("Could not complete CGK onboarding", exc_info=True)

        if granted:
            text = completion_message(interaction.guild, await self._opportunities_id(interaction))
        else:
            text = (
                "✅ Thank you! Your answers are saved and our team has them. We "
                "couldn't unlock the rest of the server automatically — our team "
                "will give you access shortly."
            )

        # In the member's own onboarding channel the message stays as a normal
        # post (so the link is still there later); elsewhere it is private.
        if self.in_ticket and interaction.channel is not None:
            post = text
            if not granted and member is not None:
                post += (
                    f"\n\n⚠️ The access role could not be granted to {member.mention} "
                    "— a moderator needs to add it."
                )
            try:
                await interaction.channel.send(post, allowed_mentions=NO_MENTIONS)
            except discord.HTTPException:
                logger.info("Could not post the completion message in %s", interaction.channel_id)
            else:
                try:
                    await interaction.delete_original_response()  # the "thinking…" note
                except discord.HTTPException:
                    pass
                return
        await interaction.followup.send(text, ephemeral=True)

    @staticmethod
    async def _opportunities_id(interaction: discord.Interaction) -> int | None:
        cog = _creator_cog(interaction)
        if cog is None or interaction.guild is None:
            return None
        try:
            return (await cog.settings(interaction.guild.id)).channels.get("opportunities")
        except Exception:  # noqa: BLE001 - the message still goes out without the link
            logger.warning("Could not read the opportunities channel", exc_info=True)
            return None


class CreatorQuestionnaireView(discord.ui.View):
    """"Start onboarding" under the rules - opens the questionnaire."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Start onboarding",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_creator_onboarding:questionnaire",
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.user.bot:
            await interaction.response.send_message(
                "Use the questionnaire in the server.", ephemeral=True
            )
            return
        owner = await ticket_owner(interaction)
        if owner is not None and owner != interaction.user.id:
            await _not_yours(interaction, owner)
            return
        await interaction.response.send_modal(
            CreatorQuestionnaireModal(interaction.user, in_ticket=owner is not None)
        )


# ── Composer ───────────────────────────────────────────────────────────────
@dataclass(slots=True)
class CreatorDraft:
    """One moderator's creator welcome, from scan to send."""

    user_id: int
    groups: list[DayGroup]
    settings: CreatorSettings
    channel_id: int | None
    selected_keys: set[str] = field(default_factory=lambda: {"all"})
    notice: tuple[str, str] | None = None

    @classmethod
    def start(
        cls, user_id: int, groups: list[DayGroup], settings: CreatorSettings
    ) -> "CreatorDraft":
        return cls(
            user_id=user_id,
            groups=groups,
            settings=settings,
            channel_id=settings.default_channel_id,
        )

    def apply_selection(self, keys: set[str]) -> None:
        self.selected_keys = {"all"} if not keys or "all" in keys else keys

    def is_active(self, key: str) -> bool:
        return "all" in self.selected_keys or key in self.selected_keys

    @property
    def selected_members(self) -> list[discord.Member]:
        unique: dict[int, discord.Member] = {
            member.id: member
            for group in self.groups
            if self.is_active(group.key)
            for member in group.members
        }
        return sorted(unique.values(), key=lambda m: m.joined_at, reverse=True)

    @property
    def is_default_channel(self) -> bool:
        return bool(self.channel_id) and self.channel_id == self.settings.default_channel_id

    def inform(self, message: str, level: str = "info") -> None:
        self.notice = (level, message)

    def take_notice(self) -> tuple[str, str] | None:
        notice, self.notice = self.notice, None
        return notice


def post_preview(tags: str = "") -> discord.Embed:
    body = f"*{tags}*\n\n{WELCOME_MESSAGE}" if tags else WELCOME_MESSAGE
    return embed_builder.accent_embed(
        "Post preview", f"{body}\n\n`[ ✅ YES ]`  `[ ❌ NO ]`"[:4000]
    )


def build_composer_embeds(draft: CreatorDraft) -> list[discord.Embed]:
    members = draft.selected_members
    lines: list[str] = []
    notice = draft.take_notice()
    if notice:
        level, text = notice
        lines += [f"{NOTICE_STYLES.get(level, 'ℹ️')} {text}", embed_builder.SEPARATOR]

    names = [member.display_name for member in members[:12]]
    preview = ", ".join(names) if names else "No members selected yet"
    if len(members) > 12:
        preview += f" … and {len(members) - 12} more"
    lines += [
        embed_builder.section("Members") + f" **{len(members)}** selected",
        preview,
        "",
        "\n".join(
            embed_builder.item(
                f"**{group.label}** — {len(group.members)}"
                + ("  ✅" if draft.is_active(group.key) else "")
            )
            for group in draft.groups
        ),
        "",
    ]
    if draft.channel_id:
        tag = "  ⭐ *default*" if draft.is_default_channel else ""
        lines.append(embed_builder.item(f"Posting in <#{draft.channel_id}>{tag}"))
    else:
        lines.append(embed_builder.item("⚠️ **No channel chosen** — pick one in the channel menu."))
    lines += [
        embed_builder.SEPARATOR,
        "Pick the days and the channel, then press **Send**. Members answer "
        "with the buttons and get private replies.",
    ]
    control = embed_builder.base_embed(
        title="👋  Creator onboarding", description="\n".join(lines)
    )

    tags = " ".join(f"@{member.display_name}" for member in members[:8])
    if len(members) > 8:
        tags += f" … +{len(members) - 8} more"
    return [control, post_preview(tags or "No members tagged")]


async def render_composer(interaction: discord.Interaction, draft: CreatorDraft) -> None:
    await replace_message(interaction, build_composer_embeds(draft), CreatorComposerView(draft))


class CreatorDaySelect(discord.ui.Select):
    def __init__(self, draft: CreatorDraft):
        total = sum(len(group.members) for group in draft.groups)
        options = [
            discord.SelectOption(
                label=f"Everyone not yet welcomed ({total})",
                value="all",
                emoji="✅",
                description=f"All members from the last {ONBOARDING_LOOKBACK_DAYS} days",
                default="all" in draft.selected_keys,
            )
        ]
        for group in draft.groups[:24]:
            options.append(
                discord.SelectOption(
                    label=f"{group.label} ({len(group.members)})",
                    value=group.key,
                    emoji="📅",
                    description=group.description[:100],
                    default=group.key in draft.selected_keys,
                )
            )
        super().__init__(
            placeholder="Which join days to welcome (pick several)...",
            min_values=1,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        draft: CreatorDraft = self.view.draft  # type: ignore[attr-defined]
        draft.apply_selection(set(self.values))
        await render_composer(interaction, draft)


class CreatorDestinationSelect(discord.ui.ChannelSelect):
    def __init__(self, draft: CreatorDraft):
        super().__init__(
            placeholder="Choose the channel to post the welcome in...",
            channel_types=TEXT_CHANNEL_TYPES,
            min_values=1,
            max_values=1,
            default_values=[discord.Object(draft.channel_id)] if draft.channel_id else [],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await ack(interaction)
        draft: CreatorDraft = self.view.draft  # type: ignore[attr-defined]
        cog = _creator_cog(interaction)
        channel = await cog.resolve_channel(interaction.guild, self.values[0].id) if cog else None
        if channel is None:
            draft.inform("That channel could not be opened. Pick another.", "error")
        else:
            draft.channel_id = channel.id
            missing = missing_permissions(channel, interaction.guild.me)
            if missing:
                draft.inform(
                    f"The bot is missing **{', '.join(missing)}** in {channel.mention}.",
                    "warning",
                )
            elif not draft.is_default_channel:
                draft.inform(
                    f"Posting in {channel.mention}. Press **⭐ Make default** to use it every time.",
                    "success",
                )
        await render_composer(interaction, draft)


class CreatorComposerView(discord.ui.View):
    def __init__(self, draft: CreatorDraft):
        super().__init__(timeout=COMPOSER_TIMEOUT)
        self.draft = draft
        self.add_item(CreatorDaySelect(draft))
        self.add_item(CreatorDestinationSelect(draft))
        count = len(draft.selected_members)
        self.make_default.disabled = not draft.channel_id or draft.is_default_channel
        self.send.label = f"Send to {count} member{'s' if count != 1 else ''}"
        self.send.disabled = count == 0 or not draft.channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.draft.user_id:
            await interaction.response.send_message(
                embed=embed_builder.error_embed(
                    "This welcome belongs to someone else",
                    "Press **🔍 Scan for new members** to start your own.",
                ),
                ephemeral=True,
            )
            return False
        return await require_manage(interaction)

    @discord.ui.button(label="Make default", style=discord.ButtonStyle.secondary, emoji="⭐", row=2)
    async def make_default(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await ack(interaction)
        cog = _creator_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Creator onboarding")
            return
        await cog.set_channel(interaction.guild.id, "welcome", self.draft.channel_id)
        self.draft.settings = await cog.settings(interaction.guild.id)
        self.draft.inform(f"<#{self.draft.channel_id}> is now the default channel.", "success")
        await render_composer(interaction, self.draft)

    @discord.ui.button(label="Send", style=discord.ButtonStyle.success, emoji="✅", row=3)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await ack(interaction)
        await _execute_delivery(interaction, self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️", row=3)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await replace_message(
            interaction, embed_builder.info_embed("Cancelled", "Nothing was sent."), None
        )
        self.stop()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        logger.exception("Creator onboarding composer control failed", exc_info=error)
        self.draft.inform(
            "That did not go through. Nothing was sent — the bot console has the details.",
            "error",
        )
        try:
            await ack(interaction)
            await render_composer(interaction, self.draft)
        except discord.HTTPException:
            logger.warning("Could not report a creator onboarding failure", exc_info=True)


async def _execute_delivery(interaction: discord.Interaction, view: CreatorComposerView) -> None:
    draft = view.draft
    cog = _creator_cog(interaction)
    if cog is None:
        await missing_cog(interaction, "Creator onboarding")
        return
    members = draft.selected_members
    if not members:
        draft.inform("Pick at least one join day first.", "warning")
        await render_composer(interaction, draft)
        return
    channel = await cog.resolve_channel(interaction.guild, draft.channel_id)
    if channel is None:
        draft.channel_id = None
        draft.inform("That channel no longer exists or the bot cannot see it.", "error")
        await render_composer(interaction, draft)
        return
    missing = missing_permissions(channel, interaction.guild.me)
    if missing:
        draft.inform(
            f"The bot needs **{', '.join(missing)}** in {channel.mention} before it can post there.",
            "error",
        )
        await render_composer(interaction, draft)
        return

    # Clearing the controls first means a second click cannot send twice.
    await replace_message(
        interaction,
        embed_builder.info_embed(
            "Sending the welcome...",
            embed_builder.item(f"Tagging **{len(members)}** member(s) in {channel.mention}"),
        ),
        None,
    )
    view.stop()

    try:
        message, marked = await cog.deliver(
            guild=interaction.guild,
            members=members,
            moderator=interaction.user,
            channel=channel,
            view=CreatorWelcomeView(),
        )
    except discord.Forbidden:
        embed = embed_builder.error_embed(
            "Missing permissions",
            "The bot could not post in that channel. Grant it **View Channel** and "
            "**Send Messages**, then scan again. Nobody was logged.",
        )
    except discord.HTTPException as exc:
        logger.exception("Creator onboarding delivery failed")
        embed = embed_builder.error_embed("Delivery failed", f"Discord rejected the welcome: {exc}")
    else:
        embed = embed_builder.success_embed(
            "Welcome sent",
            "\n".join(
                [
                    embed_builder.item(f"Members logged as welcomed: **{marked}**"),
                    embed_builder.item(f"Posted in {channel.mention} · [jump to it]({message.jump_url})"),
                ]
            ),
        )
    try:
        await interaction.edit_original_response(embeds=[embed], view=None)
    except discord.HTTPException:
        logger.info("Creator welcome finished after the interaction token expired.")


# ── Test message ───────────────────────────────────────────────────────────
class TestChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, channel_id: int | None):
        super().__init__(
            placeholder="Choose the channel to send the test message to...",
            channel_types=TEXT_CHANNEL_TYPES,
            min_values=1,
            max_values=1,
            default_values=[discord.Object(channel_id)] if channel_id else [],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: CreatorTestView = self.view  # type: ignore[assignment]
        view.channel_id = self.values[0].id
        await replace_message(interaction, build_test_embed(view.channel_id), CreatorTestView(view.channel_id))


def build_test_embed(channel_id: int | None, notice: str | None = None) -> discord.Embed:
    lines = []
    if notice:
        lines += [notice, embed_builder.SEPARATOR]
    lines += [
        "Sends the real interactive message — **✅ YES / ❌ NO** and every "
        "private reply behind them — so you can click through it yourself.",
        "",
        embed_builder.item("Nobody is tagged and nobody is logged as welcomed."),
        embed_builder.item(
            f"Destination: <#{channel_id}>" if channel_id else "Destination: *pick a channel below*"
        ),
    ]
    return embed_builder.base_embed(title="🧪  Test the creator welcome", description="\n".join(lines))


class CreatorTestView(discord.ui.View):
    def __init__(self, channel_id: int | None = None):
        super().__init__(timeout=COMPOSER_TIMEOUT)
        self.channel_id = channel_id
        self.add_item(TestChannelSelect(channel_id))
        self.send_test.disabled = not channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage(interaction)

    @discord.ui.button(label="Send test message", style=discord.ButtonStyle.success, emoji="🧪", row=1)
    async def send_test(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await ack(interaction)
        cog = _creator_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Creator onboarding")
            return
        channel = await cog.resolve_channel(interaction.guild, self.channel_id)
        if channel is None:
            await replace_message(
                interaction,
                build_test_embed(None, "❌ That channel could not be opened. Pick another."),
                CreatorTestView(None),
            )
            return
        missing = missing_permissions(channel, interaction.guild.me)
        if missing:
            await replace_message(
                interaction,
                build_test_embed(
                    channel.id,
                    f"❌ The bot needs **{', '.join(missing)}** in {channel.mention}.",
                ),
                CreatorTestView(channel.id),
            )
            return
        try:
            message = await cog.post_welcome(channel, [], CreatorWelcomeView())
        except discord.HTTPException as exc:
            logger.warning("Creator onboarding test failed: %s", exc)
            await replace_message(
                interaction,
                build_test_embed(channel.id, f"❌ Discord rejected the test message: {exc}"),
                CreatorTestView(channel.id),
            )
            return
        await replace_message(
            interaction,
            build_test_embed(
                channel.id,
                f"✅ Test message sent to {channel.mention} · [jump to it]({message.jump_url})",
            ),
            CreatorTestView(channel.id),
        )

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, emoji="✖️", row=1)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await replace_message(
            interaction, embed_builder.info_embed("Test closed", "Nothing else was sent."), None
        )
        self.stop()


# ── Settings ───────────────────────────────────────────────────────────────
def build_settings_embed(settings: CreatorSettings, notice: str | None = None) -> discord.Embed:
    lines = []
    if notice:
        lines += [f"✅ {notice}", embed_builder.SEPARATOR]
    lines.append(
        embed_builder.item(
            f"**{CHANNEL_LABELS['welcome']}:** "
            f"{_channel_line(settings.channels.get('welcome'), settings.sources['welcome'])}"
        )
        + f"\n*{CHANNEL_HINTS['welcome']}*"
    )
    lines.append(
        embed_builder.item(
            f"**{CHANNEL_LABELS['getting_started']}:** {_getting_started_line(settings)}"
        )
        + f"\n*{CHANNEL_HINTS['getting_started']}*"
    )
    lines.append(
        embed_builder.item(
            f"**{CHANNEL_LABELS['opportunities']}:** "
            f"{_channel_line(settings.channels.get('opportunities'), settings.sources['opportunities'])}"
        )
        + f"\n*{CHANNEL_HINTS['opportunities']}*"
    )
    lines += [
        embed_builder.SEPARATOR,
        "Pick a channel in a menu to change it; clear a menu to unset it. "
        "Everything saves instantly and survives restarts.",
    ]
    return embed_builder.base_embed(
        title="⚙️  Creator onboarding settings", description="\n".join(lines)
    )


class CreatorSettingsSelect(discord.ui.ChannelSelect):
    def __init__(self, key: str, row: int, settings: CreatorSettings):
        current = settings.channels.get(key)
        super().__init__(
            placeholder=f"{CHANNEL_LABELS[key]} — not set",
            channel_types=TEXT_CHANNEL_TYPES,
            min_values=0,
            max_values=1,
            default_values=[discord.Object(current)] if current else [],
            row=row,
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction) -> None:
        await ack(interaction)
        cog = _creator_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Creator onboarding")
            return
        chosen = self.values[0].id if self.values else None
        await cog.set_channel(interaction.guild.id, self.key, chosen)
        label = CHANNEL_LABELS[self.key]
        notice = f"{label} set to <#{chosen}>." if chosen else f"{label} cleared."
        settings = await cog.settings(interaction.guild.id)
        await replace_message(
            interaction, build_settings_embed(settings, notice), CreatorSettingsView(settings)
        )


class CreatorSettingsView(discord.ui.View):
    def __init__(self, settings: CreatorSettings):
        super().__init__(timeout=COMPOSER_TIMEOUT)
        for row, key in enumerate(CHANNEL_LABELS):
            self.add_item(CreatorSettingsSelect(key, row, settings))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage(interaction)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, emoji="✅", row=3)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await replace_message(
            interaction,
            embed_builder.success_embed("Settings saved", "Creator onboarding is ready to use."),
            None,
        )
        self.stop()


# ── Reset confirmation ─────────────────────────────────────────────────────
class CreatorResetView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @discord.ui.button(label="Yes, clear the creator log", style=discord.ButtonStyle.danger, emoji="♻️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        await ack(interaction)
        cog = _creator_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Creator onboarding")
            return
        cleared = await cog.clear_onboarded(interaction.guild.id)
        await replace_message(
            interaction,
            embed_builder.success_embed(
                "Creator onboarding log cleared",
                embed_builder.item(f"Removed **{cleared}** logged member(s).")
                + "\nEveryone who joined recently can be welcomed again.",
            ),
            None,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await replace_message(
            interaction, embed_builder.info_embed("Cancelled", "The log was left untouched."), None
        )
        self.stop()


# ── Persistent hub ─────────────────────────────────────────────────────────
async def build_creator_hub_embed(interaction: discord.Interaction) -> discord.Embed:
    cog = _creator_cog(interaction)
    if cog is None:
        return embed_builder.error_embed(
            "Creator onboarding unavailable", "The creator onboarding module did not load."
        )
    stats = await cog.stats(interaction.guild)
    settings = await cog.settings(interaction.guild.id)
    blocks = [
        "Tag new members in one post that asks **Are you a TikTok Shop creator?** "
        "with ✅ YES / ❌ NO buttons. Each member gets a private reply based on "
        "their answer.",
        embed_builder.SEPARATOR,
        embed_builder.section("Right now"),
        "\n".join(
            [
                embed_builder.item(f"Waiting to be welcomed: **{stats['pending']}**"),
                embed_builder.item(f"Welcomed in the last 7 days: **{stats['last_7_days']}**"),
                embed_builder.item(f"Welcomed all-time: **{stats['total']}**"),
            ]
        ),
        "",
        embed_builder.section("Answers"),
        "\n".join(
            [
                embed_builder.item(f"✅ TikTok Shop creators: **{stats['yes']}**"),
                embed_builder.item(f"🌱 Still learning: **{stats['learning']}**"),
                embed_builder.item(f"🔥 Experienced: **{stats['experienced']}**"),
                embed_builder.item(f"❌ Not a creator yet: **{stats['no']}**"),
            ]
        ),
        "",
        embed_builder.section("Setup"),
        "\n".join(
            [
                embed_builder.item(
                    f"**{CHANNEL_LABELS['welcome']}:** "
                    f"{_channel_line(settings.channels.get('welcome'), settings.sources['welcome'])}"
                ),
                embed_builder.item(
                    f"**{CHANNEL_LABELS['getting_started']}:** {_getting_started_line(settings)}"
                ),
                embed_builder.item(
                    f"**{CHANNEL_LABELS['opportunities']}:** "
                    f"{_channel_line(settings.channels.get('opportunities'), settings.sources['opportunities'])}"
                ),
            ]
        ),
    ]
    return embed_builder.base_embed(title="👋  Creator Onboarding", description="\n".join(blocks))


class CreatorOnboardingHubView(discord.ui.View):
    """Persistent creator onboarding hub (static custom_ids, survives restarts)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Scan for new members",
        style=discord.ButtonStyle.success,
        custom_id="cgk_creator_onboarding_hub:scan",
        emoji="🔍",
        row=0,
    )
    async def scan(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        cog = _creator_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Creator onboarding")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        pending = await cog.pending_members(interaction.guild)
        if not pending:
            await interaction.followup.send(
                embed=embed_builder.success_embed(
                    "Everyone is welcomed",
                    f"No member who joined in the last {ONBOARDING_LOOKBACK_DAYS} days "
                    "is waiting for the creator welcome.",
                ),
                ephemeral=True,
            )
            return

        settings = await cog.settings(interaction.guild.id)
        draft = CreatorDraft.start(interaction.user.id, cog.group_by_day(pending), settings)
        if draft.channel_id:
            if await cog.resolve_channel(interaction.guild, draft.channel_id) is None:
                draft.channel_id = None
                draft.inform(
                    "Your default channel no longer exists. Pick a channel below, "
                    "then press **⭐ Make default**.",
                    "warning",
                )
        else:
            draft.inform(
                "No default channel yet. Pick one below and press **⭐ Make default** "
                "to remember it.",
                "info",
            )
        await interaction.followup.send(
            embeds=build_composer_embeds(draft),
            view=CreatorComposerView(draft),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="Test message",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_creator_onboarding_hub:test",
        emoji="🧪",
        row=0,
    )
    async def test(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        await interaction.response.send_message(
            embed=build_test_embed(None), view=CreatorTestView(), ephemeral=True
        )

    @discord.ui.button(
        label="Settings",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_creator_onboarding_hub:settings",
        emoji="⚙️",
        row=0,
    )
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        cog = _creator_cog(interaction)
        if cog is None:
            await missing_cog(interaction, "Creator onboarding")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        settings = await cog.settings(interaction.guild.id)
        await interaction.followup.send(
            embed=build_settings_embed(settings), view=CreatorSettingsView(settings), ephemeral=True
        )

    @discord.ui.button(
        label="Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_creator_onboarding_hub:stats",
        emoji="📋",
        row=1,
    )
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(embed=await build_creator_hub_embed(interaction), ephemeral=True)

    @discord.ui.button(
        label="Reset creator log",
        style=discord.ButtonStyle.danger,
        custom_id="cgk_creator_onboarding_hub:reset",
        emoji="♻️",
        row=1,
    )
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        await interaction.response.send_message(
            embed=embed_builder.warning_embed(
                "Clear the creator onboarding log?",
                "Every member who joined recently becomes selectable again, so they "
                "can receive the creator welcome a second time. Their answers are "
                "kept. This cannot be undone.",
            ),
            view=CreatorResetView(),
            ephemeral=True,
        )


__all__ = [
    "CreatorComposerView",
    "CreatorDraft",
    "CreatorJourneyView",
    "CreatorQuestionnaireModal",
    "CreatorQuestionnaireView",
    "CreatorOnboardingHubView",
    "CreatorSettingsView",
    "CreatorTestView",
    "CreatorWelcomeView",
    "Shop101DoneView",
    "build_composer_embeds",
    "build_creator_hub_embed",
    "build_settings_embed",
    "build_test_embed",
]
