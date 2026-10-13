"""
Moderator interface for CGK Onboarding (private per-member channels).
Created by Aljay Leodones for CGK Linens.

Flow:  Scan  ->  pick the join days  ->  Open onboarding channels.

Each selected member gets a private ``#<handle>-onboarding`` channel where
they are tagged with the creator questions. The scan screen can also clear
the most recently tagged group and rescan, so those members can be tagged
again (their existing channel is reused, never duplicated).

The member side lives in ``views.creator_onboarding_view`` and is shared
with the public Onboarding post.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

import discord

from cogs.cgk_onboarding import (
    CATEGORY_LIMIT,
    CategoryFull,
    CGKSettings,
    TaggedGroup,
    TicketResult,
)
from cogs.creator_onboarding import SHOP_101_CHECKPOINT_MESSAGE
from cogs.onboarding import DayGroup, missing_permissions
from config import ONBOARDING_LOOKBACK_DAYS
from utils import embed_builder
from views.common import ack, missing_cog, replace_message, require_manage
from views.creator_onboarding_view import OnboardingTicketView, Shop101DoneView

logger = logging.getLogger("cgk_bot.cgk_onboarding_ui")

COMPOSER_TIMEOUT = 900
NOTICE_STYLES = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}
SOURCE_LABELS = {"saved": "", "env": " *(default)*", "unset": ""}
NO_MENTIONS = discord.AllowedMentions.none()


def _cog(interaction: discord.Interaction):
    return interaction.client.get_cog("CGKOnboardingCog")


def _category_line(guild: discord.Guild, settings: CGKSettings) -> str:
    if not settings.category_id:
        return "*not set*"
    category = guild.get_channel(settings.category_id)
    name = f"**{category.name}**" if category else f"*missing* (`{settings.category_id}`)"
    return name + SOURCE_LABELS.get(settings.sources["category"], "")


def _role_line(settings: CGKSettings) -> str:
    if not settings.role_id:
        return "*not set*"
    return f"<@&{settings.role_id}>" + SOURCE_LABELS.get(settings.sources["role"], "")


def _problem_lines(problems: list[str]) -> list[str]:
    return [embed_builder.item(f"⚠️ {problem}") for problem in problems]


# ── Scan composer ──────────────────────────────────────────────────────────
@dataclass(slots=True)
class CGKDraft:
    """One moderator's scan, from the member list to the send."""

    user_id: int
    groups: list[DayGroup]
    settings: CGKSettings
    last_group: TaggedGroup | None
    problems: list[str]
    selected_keys: set[str] = field(default_factory=lambda: {"all"})
    selected_member_id: int | None = None
    notice: tuple[str, str] | None = None

    def apply_selection(self, keys: set[str]) -> None:
        self.selected_member_id = None
        self.selected_keys = {"all"} if not keys or "all" in keys else keys

    def select_single_member(self, member_id: int | None) -> None:
        self.selected_member_id = member_id

    def is_active(self, key: str) -> bool:
        return "all" in self.selected_keys or key in self.selected_keys

    @property
    def all_pending_members(self) -> list[discord.Member]:
        seen: set[int] = set()
        result: list[discord.Member] = []
        for group in self.groups:
            for member in group.members:
                if member.id not in seen:
                    seen.add(member.id)
                    result.append(member)
        return sorted(
            result,
            key=lambda m: getattr(m, "joined_at", None) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @property
    def selected_members(self) -> list[discord.Member]:
        if self.selected_member_id is not None:
            for member in self.all_pending_members:
                if member.id == self.selected_member_id:
                    return [member]
            self.selected_member_id = None

        unique: dict[int, discord.Member] = {
            member.id: member
            for group in self.groups
            if self.is_active(group.key)
            for member in group.members
        }
        return sorted(
            unique.values(),
            key=lambda m: getattr(m, "joined_at", None) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    def inform(self, message: str, level: str = "info") -> None:
        self.notice = (level, message)

    def take_notice(self) -> tuple[str, str] | None:
        notice, self.notice = self.notice, None
        return notice


def build_composer_embed(draft: CGKDraft, guild: discord.Guild) -> discord.Embed:
    members = draft.selected_members
    lines: list[str] = []
    notice = draft.take_notice()
    if notice:
        level, text = notice
        lines += [f"{NOTICE_STYLES.get(level, 'ℹ️')} {text}", embed_builder.SEPARATOR]

    if draft.groups:
        if draft.selected_member_id is not None and members:
            target = members[0]
            joined_text = (
                f" · Joined <t:{int(target.joined_at.timestamp())}:R>"
                if getattr(target, "joined_at", None)
                else ""
            )
            lines += [
                embed_builder.section("Single member mode") + " **1** member selected",
                embed_builder.item(f"Target: **{target.display_name}** ({target.mention}){joined_text}"),
                embed_builder.item(f"Member ID: `{target.id}`"),
                "",
                "*(Only this single member will have an onboarding channel opened. "
                "Select 'None' in the member menu or pick a join day to switch back)*",
            ]
        else:
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
            ]
    else:
        lines.append(
            f"✅ Everyone who joined in the last {ONBOARDING_LOOKBACK_DAYS} days "
            "has been tagged (or already has access)."
        )


    lines += [
        "",
        embed_builder.section("What happens"),
        embed_builder.item(
            "Each member gets a private **#handle-onboarding** channel in "
            f"{_category_line(guild, draft.settings)} — only they and the moderators can see it."
        ),
        embed_builder.item(
            "They're tagged there with the TikTok Shop questions, the rules and the questionnaire."
        ),
        embed_builder.item(
            f"Finishing the questionnaire grants {_role_line(draft.settings)}. "
            "Members who already have it are skipped."
        ),
    ]
    if draft.problems:
        lines += ["", embed_builder.section("Fix before sending"), *_problem_lines(draft.problems)]

    lines.append("")
    if draft.last_group:
        group = draft.last_group
        lines.append(
            embed_builder.section("Last tagged group")
            + f" **{group.count}** member{'s' if group.count != 1 else ''} · "
            f"<t:{int(group.tagged_at)}:R>"
        )
        lines.append(
            "Press **♻️ Clear last tagged group & rescan** to tag them again — "
            "their existing channels are reused."
        )
    else:
        lines.append(embed_builder.section("Last tagged group") + " *none yet*")
    return embed_builder.base_embed(title="🎟️  CGK Onboarding", description="\n".join(lines))


async def _draft_for(interaction: discord.Interaction, user_id: int) -> CGKDraft:
    cog = _cog(interaction)
    settings = await cog.settings(interaction.guild.id)
    pending = await cog.pending_members(interaction.guild, settings)
    return CGKDraft(
        user_id=user_id,
        groups=cog.group_by_day(pending),
        settings=settings,
        last_group=await cog.last_group(interaction.guild.id),
        problems=cog.setup_problems(interaction.guild, settings),
    )


async def render_composer(interaction: discord.Interaction, draft: CGKDraft) -> None:
    await replace_message(
        interaction, build_composer_embed(draft, interaction.guild), CGKComposerView(draft)
    )


class CGKDaySelect(discord.ui.Select):
    def __init__(self, draft: CGKDraft):
        total = sum(len(group.members) for group in draft.groups)
        options = [
            discord.SelectOption(
                label=f"Everyone not yet tagged ({total})",
                value="all",
                emoji="✅",
                description=f"All members from the last {ONBOARDING_LOOKBACK_DAYS} days",
                default="all" in draft.selected_keys and draft.selected_member_id is None,
            )
        ]
        for group in draft.groups[:24]:
            options.append(
                discord.SelectOption(
                    label=f"{group.label} ({len(group.members)})",
                    value=group.key,
                    emoji="📅",
                    description=group.description[:100],
                    default=group.key in draft.selected_keys and draft.selected_member_id is None,
                )
            )
        super().__init__(
            placeholder="Which join days to onboard (pick several)...",
            min_values=1,
            max_values=len(options),
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        draft: CGKDraft = self.view.draft  # type: ignore[attr-defined]
        draft.apply_selection(set(self.values))
        await render_composer(interaction, draft)


class CGKSingleMemberSelect(discord.ui.Select):
    """Select a specific single member from the new members list to onboard."""

    def __init__(self, draft: CGKDraft):
        pending = draft.all_pending_members
        options = [
            discord.SelectOption(
                label="None (use join days above)",
                value="none",
                emoji="↩️",
                description="Onboard members based on the join days selected above",
                default=draft.selected_member_id is None,
            )
        ]
        for member in pending[:24]:
            joined_str = (
                member.joined_at.strftime("%b %d, %H:%M")
                if getattr(member, "joined_at", None)
                else "recently"
            )
            name_tag = getattr(member, "name", getattr(member, "display_name", str(member.id)))
            disp_name = getattr(member, "display_name", str(member.id))
            options.append(
                discord.SelectOption(
                    label=disp_name[:100],
                    value=str(member.id),
                    emoji="👤",
                    description=f"@{name_tag} · Joined {joined_str}"[:100],
                    default=draft.selected_member_id == member.id,
                )
            )

        super().__init__(
            placeholder="Or onboard a single member from the list...",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        draft: CGKDraft = self.view.draft  # type: ignore[attr-defined]
        chosen = self.values[0]
        if chosen == "none":
            draft.select_single_member(None)
        else:
            draft.select_single_member(int(chosen))
        await render_composer(interaction, draft)


class CGKComposerMemberPickerView(discord.ui.View):
    """Allows searching and selecting any member for single-member onboarding."""

    def __init__(self, draft: CGKDraft, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.draft = draft

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Search for a member to onboard...",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def select_user(
        self, interaction: discord.Interaction, select: discord.ui.UserSelect
    ) -> None:
        if not await require_manage(interaction):
            return
        if not select.values:
            return
        user = select.values[0]
        member = interaction.guild.get_member(user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user.id)
            except (discord.NotFound, discord.HTTPException):
                await interaction.response.send_message(
                    "That member could not be found in this server.", ephemeral=True
                )
                return
        if member.bot:
            await interaction.response.send_message(
                "Bots can't be onboarded.", ephemeral=True
            )
            return

        self.draft.select_single_member(member.id)
        pending_ids = {m.id for m in self.draft.all_pending_members}
        if member.id not in pending_ids:
            self.draft.groups.insert(0, DayGroup("custom", "Selected member", "", [member]))

        self.draft.inform(f"Selected **{member.display_name}** for single-member onboarding.", "success")
        await render_composer(interaction, self.draft)

    @discord.ui.button(label="Back to scan", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await render_composer(interaction, self.draft)


class CGKComposerView(discord.ui.View):
    def __init__(self, draft: CGKDraft):
        super().__init__(timeout=COMPOSER_TIMEOUT)
        self.draft = draft
        if draft.groups:
            self.add_item(CGKDaySelect(draft))
            if draft.all_pending_members:
                self.add_item(CGKSingleMemberSelect(draft))
        count = len(draft.selected_members)
        if draft.selected_member_id is not None and count == 1:
            member = draft.selected_members[0]
            disp = getattr(member, "display_name", str(member.id))
            self.send.label = f"Open onboarding for {disp[:20]}"
        else:
            self.send.label = f"Open {count} onboarding channel{'s' if count != 1 else ''}"

        self.send.disabled = count == 0 or bool(draft.problems)
        self.clear_and_rescan.disabled = draft.last_group is None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.draft.user_id:
            await interaction.response.send_message(
                embed=embed_builder.error_embed(
                    "This scan belongs to someone else",
                    "Press **🔍 Scan for new members** to start your own.",
                ),
                ephemeral=True,
            )
            return False
        return await require_manage(interaction)

    @discord.ui.button(label="Open onboarding channels", style=discord.ButtonStyle.success, emoji="🎟️", row=2)
    async def send(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await ack(interaction)
        await _execute_delivery(interaction, self)

    @discord.ui.button(label="Find member", style=discord.ButtonStyle.secondary, emoji="🔍", row=2)
    async def search_member(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        await replace_message(
            interaction,
            embed_builder.base_embed(
                title="🔍  Select a Member to Onboard",
                description=(
                    f"{embed_builder.SEPARATOR}\n"
                    "Search and select any member to onboard individually in a private channel."
                ),
            ),
            CGKComposerMemberPickerView(self.draft),
        )

    @discord.ui.button(
        label="Clear last tagged group & rescan",
        style=discord.ButtonStyle.secondary,
        emoji="♻️",
        row=2,
    )
    async def clear_and_rescan(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await ack(interaction)
        cog = _cog(interaction)
        if cog is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        cleared = await cog.clear_last_group(interaction.guild.id)
        draft = await _draft_for(interaction, self.draft.user_id)
        draft.inform(
            f"Cleared **{cleared}** member{'s' if cleared != 1 else ''} from the last tagged "
            "group — anyone who still needs onboarding is back in the list.",
            "success",
        )
        await render_composer(interaction, draft)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️", row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await replace_message(
            interaction, embed_builder.info_embed("Cancelled", "Nothing was sent."), None
        )
        self.stop()


    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        logger.exception("CGK onboarding composer control failed", exc_info=error)
        self.draft.inform(
            "That did not go through — the bot console has the details.", "error"
        )
        try:
            await ack(interaction)
            await render_composer(interaction, self.draft)
        except discord.HTTPException:
            logger.warning("Could not report a CGK onboarding failure", exc_info=True)


def _result_lines(result: TicketResult) -> list[str]:
    lines = [
        embed_builder.item(f"New onboarding channels: **{len(result.created)}**"),
        embed_builder.item(f"Existing channels re-tagged: **{len(result.reused)}**"),
    ]
    channels = [channel.mention for channel in (result.created + result.reused)[:15]]
    if channels:
        lines.append(embed_builder.item(" ".join(channels)))
    if result.failed:
        lines.append(embed_builder.item(f"Could not open: **{len(result.failed)}**"))
        lines += [
            embed_builder.item(f"{name} — {reason}") for name, reason in result.failed[:10]
        ]
    return lines


async def _execute_delivery(interaction: discord.Interaction, view: CGKComposerView) -> None:
    draft = view.draft
    cog = _cog(interaction)
    if cog is None:
        await missing_cog(interaction, "CGK Onboarding")
        return
    members = draft.selected_members
    if not members:
        draft.inform("Pick at least one join day first.", "warning")
        await render_composer(interaction, draft)
        return
    settings = await cog.settings(interaction.guild.id)
    problems = cog.setup_problems(interaction.guild, settings)
    if problems:
        draft.problems = problems
        draft.inform("Fix the setup below before sending.", "error")
        await render_composer(interaction, draft)
        return

    def working(done: int = 0) -> discord.Embed:
        return embed_builder.info_embed(
            "Opening onboarding channels...",
            embed_builder.item(f"Done: **{done}/{len(members)}** (about one per second)"),
        )

    # Clearing the controls first means a second click cannot send twice.
    await replace_message(interaction, working(), None)
    view.stop()

    async def progress(done: int, total: int) -> None:
        await interaction.edit_original_response(embeds=[working(done)], view=None)

    try:
        result = await cog.deliver(
            guild=interaction.guild,
            members=members,
            moderator=interaction.user,
            batch_id=interaction.id,
            view_factory=OnboardingTicketView,
            progress=progress,
        )
    except (ValueError, discord.HTTPException) as exc:
        logger.exception("CGK onboarding delivery failed")
        embed = embed_builder.error_embed("Could not open the channels", str(exc)[:500])
    else:
        title = "Onboarding channels opened" if result.opened else "No channels opened"
        builder = embed_builder.success_embed if result.opened else embed_builder.error_embed
        embed = builder(title, "\n".join(_result_lines(result)))
    try:
        await interaction.edit_original_response(embeds=[embed], view=None)
    except discord.HTTPException:
        logger.info("CGK onboarding finished after the interaction token expired.")


# ── Settings ───────────────────────────────────────────────────────────────
def build_settings_embed(
    guild: discord.Guild, settings: CGKSettings, problems: list[str], notice: str | None = None
) -> discord.Embed:
    lines = []
    if notice:
        lines += [f"✅ {notice}", embed_builder.SEPARATOR]
    lines += [
        embed_builder.item(f"**Onboarding category:** {_category_line(guild, settings)}")
        + f"\n*Where the private #handle-onboarding channels are created (max {CATEGORY_LIMIT} per category).*",
        embed_builder.item(f"**Access role:** {_role_line(settings)}")
        + "\n*Granted when a member finishes the questionnaire — unlocks the rest of the server.*",
    ]
    if problems:
        lines += ["", embed_builder.section("Needs attention"), *_problem_lines(problems)]
    lines += [
        embed_builder.SEPARATOR,
        "The TikTok Shop 101 link is set in **👋 Onboarding → ⚙️ Settings**.",
    ]
    return embed_builder.base_embed(title="⚙️  CGK Onboarding settings", description="\n".join(lines))


async def _render_settings(interaction: discord.Interaction, notice: str | None = None) -> None:
    cog = _cog(interaction)
    settings = await cog.settings(interaction.guild.id)
    problems = cog.setup_problems(interaction.guild, settings)
    await replace_message(
        interaction,
        build_settings_embed(interaction.guild, settings, problems, notice),
        CGKSettingsView(settings),
    )


class CGKCategorySelect(discord.ui.ChannelSelect):
    def __init__(self, settings: CGKSettings):
        super().__init__(
            placeholder="Onboarding category — not set",
            channel_types=[discord.ChannelType.category],
            min_values=0,
            max_values=1,
            default_values=[discord.Object(settings.category_id)] if settings.category_id else [],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await ack(interaction)
        chosen = self.values[0].id if self.values else None
        await _cog(interaction).set_value(interaction.guild.id, "category", chosen)
        await _render_settings(
            interaction, "Onboarding category saved." if chosen else "Category reset to the default."
        )


class CGKRoleSelect(discord.ui.RoleSelect):
    def __init__(self, settings: CGKSettings):
        super().__init__(
            placeholder="Access role — not set",
            min_values=0,
            max_values=1,
            default_values=[discord.Object(settings.role_id)] if settings.role_id else [],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await ack(interaction)
        chosen = self.values[0].id if self.values else None
        await _cog(interaction).set_value(interaction.guild.id, "role", chosen)
        await _render_settings(
            interaction, f"Access role set to <@&{chosen}>." if chosen else "Role reset to the default."
        )


class CGKSettingsView(discord.ui.View):
    def __init__(self, settings: CGKSettings):
        super().__init__(timeout=COMPOSER_TIMEOUT)
        self.add_item(CGKCategorySelect(settings))
        self.add_item(CGKRoleSelect(settings))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await require_manage(interaction)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, emoji="✅", row=2)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await replace_message(
            interaction,
            embed_builder.success_embed("Settings saved", "CGK Onboarding is ready to use."),
            None,
        )
        self.stop()


async def open_test_channel(interaction: discord.Interaction, member: discord.Member) -> None:
    """
    Opens (or re-tags) a private onboarding channel for one member as a test.

    The member is not added to any tagged group, so scans still list them.
    Replies privately.
    """
    cog = _cog(interaction)
    if cog is None:
        await missing_cog(interaction, "CGK Onboarding")
        return
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)
    settings = await cog.settings(interaction.guild.id)
    problems = cog.setup_problems(interaction.guild, settings)
    category = cog.category(interaction.guild, settings)
    if category is None or any("Manage Channels" in problem for problem in problems):
        await interaction.followup.send(
            embed=embed_builder.error_embed("Fix the setup first", "\n".join(_problem_lines(problems))),
            ephemeral=True,
        )
        return
    try:
        channel, created = await cog.open_ticket(
            member, category, OnboardingTicketView(), batch_id=None, tagged_by=None
        )
    except CategoryFull:
        await interaction.followup.send(
            embed=embed_builder.error_embed(
                "Could not open the test channel",
                f"The **{category.name}** category is full ({CATEGORY_LIMIT} channels).",
            ),
            ephemeral=True,
        )
        return
    except discord.HTTPException as exc:
        await interaction.followup.send(
            embed=embed_builder.error_embed("Could not open the test channel", str(exc)[:500]),
            ephemeral=True,
        )
        return
    yourself = member.id == interaction.user.id
    who = "you" if yourself else member.mention
    lines = [
        embed_builder.item(
            f"{'Opened' if created else 'Re-tagged ' + who + ' in'} {channel.mention}"
            + (" — click through it like a new member would." if yourself else ".")
        ),
        embed_builder.item(
            "Submitting the questionnaire really saves the answers for Slack and grants the access role."
        ),
        embed_builder.item(
            "Not added to any tagged group. Press **🔒 Close onboarding** in the channel when done."
        ),
    ]
    if problems:
        lines += ["", *_problem_lines(problems)]
    await interaction.followup.send(
        embed=embed_builder.success_embed("Test channel ready", "\n".join(lines)),
        ephemeral=True,
        allowed_mentions=NO_MENTIONS,
    )


class CGKTestMemberSelectView(discord.ui.View):
    """Allows a moderator to select any member to test the onboarding flow."""

    def __init__(self, timeout: float = 300):
        super().__init__(timeout=timeout)

    @discord.ui.select(
        cls=discord.ui.UserSelect,
        placeholder="Select a member to test onboarding on...",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def select_member(
        self, interaction: discord.Interaction, select: discord.ui.UserSelect
    ) -> None:
        if not await require_manage(interaction):
            return
        if not select.values:
            return
        user = select.values[0]
        member = interaction.guild.get_member(user.id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user.id)
            except (discord.NotFound, discord.HTTPException):
                await interaction.response.send_message(
                    "That member could not be found in this server.", ephemeral=True
                )
                return
        if member.bot:
            await interaction.response.send_message(
                "Bots can't be onboarded.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await open_test_channel(interaction, member)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️", row=1)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await replace_message(
            interaction, embed_builder.info_embed("Cancelled", "Test onboarding was cancelled."), None
        )
        self.stop()


# ── Persistent hub ─────────────────────────────────────────────────────────
async def build_cgk_hub_embed(interaction: discord.Interaction) -> discord.Embed:
    cog = _cog(interaction)
    if cog is None:
        return embed_builder.error_embed(
            "CGK Onboarding unavailable", "The CGK onboarding module did not load."
        )
    guild = interaction.guild
    settings = await cog.settings(guild.id)
    stats = await cog.stats(guild)
    problems = cog.setup_problems(guild, settings)
    creator = interaction.client.get_cog("CreatorOnboardingCog")
    answers = await creator.stats(guild) if creator else None

    blocks = [
        "Give every new member a private **#handle-onboarding** channel, tag them "
        "there with the TikTok Shop questions, the community rules and the "
        "questionnaire. Finishing it unlocks the rest of the server.",
        embed_builder.SEPARATOR,
        embed_builder.section("Right now"),
        "\n".join(
            [
                embed_builder.item(f"Waiting to be tagged: **{stats['pending']}**"),
                embed_builder.item(f"Open onboarding channels: **{stats['channels']}**"),
                embed_builder.item(f"Finished onboarding: **{stats['completed']}**"),
            ]
        ),
    ]
    if answers:
        blocks += [
            "",
            embed_builder.section("Answers (all onboarding posts)"),
            embed_builder.item(
                f"✅ **{answers['yes']}** · 🌱 **{answers['learning']}** · "
                f"🔥 **{answers['experienced']}** · ❌ **{answers['no']}**"
            ),
        ]
    blocks += [
        "",
        embed_builder.section("Setup"),
        embed_builder.item(f"**Category:** {_category_line(guild, settings)}"),
        embed_builder.item(f"**Access role:** {_role_line(settings)}"),
        *_problem_lines(problems),
        "",
        embed_builder.section("How to use it"),
        embed_builder.item(
            "**🧪 Test on myself / member** (or `/test-onboarding`) opens a test channel to click through."
        ),
        embed_builder.item(
            "**🔒 Close onboarding** in a channel lets the member or any moderator delete it."
        ),
        embed_builder.item(
            "**🔍 Scan** groups recent members by join day — or select a **single member** to onboard individually."
        ),
        embed_builder.item(
            "**📌 Post Shop 101 checkpoint** adds an *I've finished TikTok Shop 101* "
            "button to that channel, so 🌱 creators can continue from there."
        ),
    ]
    return embed_builder.base_embed(title="🎟️  CGK Onboarding", description="\n".join(blocks))


class CGKOnboardingHubView(discord.ui.View):
    """Persistent CGK Onboarding hub (static custom_ids, survives restarts)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Scan for new members",
        style=discord.ButtonStyle.success,
        custom_id="cgk_onboarding_hub:scan",
        emoji="🔍",
        row=0,
    )
    async def scan(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        if _cog(interaction) is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        draft = await _draft_for(interaction, interaction.user.id)
        await interaction.followup.send(
            embed=build_composer_embed(draft, interaction.guild),
            view=CGKComposerView(draft),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(
        label="Onboard single member",
        style=discord.ButtonStyle.success,
        custom_id="cgk_onboarding_hub:single_member",
        emoji="👤",
        row=0,
    )
    async def single_member(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        if _cog(interaction) is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        draft = await _draft_for(interaction, interaction.user.id)
        if not draft.all_pending_members:
            await interaction.followup.send(
                embed=embed_builder.info_embed(
                    "No pending new members",
                    f"Everyone who joined in the last {ONBOARDING_LOOKBACK_DAYS} days "
                    "has already been tagged or finished onboarding.",
                ),
                ephemeral=True,
            )
            return
        draft.select_single_member(draft.all_pending_members[0].id)
        draft.inform(
            f"Selected **{draft.all_pending_members[0].display_name}**. Use the dropdown to choose another member.",
            "info",
        )
        await interaction.followup.send(
            embed=build_composer_embed(draft, interaction.guild),
            view=CGKComposerView(draft),
            ephemeral=True,
            allowed_mentions=NO_MENTIONS,
        )

    @discord.ui.button(
        label="Test on myself",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_onboarding_hub:test",
        emoji="🧪",
        row=0,
    )
    async def test(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        cog = _cog(interaction)
        if cog is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await open_test_channel(interaction, interaction.user)

    @discord.ui.button(
        label="Test on member",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_onboarding_hub:test_member",
        emoji="🧪",
        row=0,
    )
    async def test_member(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        cog = _cog(interaction)
        if cog is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        embed = embed_builder.base_embed(
            title="🧪  Test CGK Onboarding on a Member",
            description=(
                f"{embed_builder.SEPARATOR}\n"
                "Select any member from the menu below to open a private test onboarding "
                "channel for them without adding them to a tagged group.\n\n"
                f"{embed_builder.item('A private **#<handle>-onboarding** channel will be opened.')}\n"
                f"{embed_builder.item('They will be tagged with the creator questions.')}\n"
                f"{embed_builder.item('Use **🔒 Close onboarding** inside the channel when finished.')}"
            ),
        )
        await interaction.response.send_message(
            embed=embed, view=CGKTestMemberSelectView(), ephemeral=True
        )

    @discord.ui.button(
        label="Post Shop 101 checkpoint",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_onboarding_hub:checkpoint",
        emoji="📌",
        row=1,
    )
    async def checkpoint(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        creator = interaction.client.get_cog("CreatorOnboardingCog")
        if creator is None:
            await missing_cog(interaction, "Creator onboarding")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel_id = (await creator.settings(interaction.guild.id)).channels.get("getting_started")
        channel = await creator.resolve_channel(interaction.guild, channel_id)
        if channel is None:
            await interaction.followup.send(
                embed=embed_builder.error_embed(
                    "TikTok Shop 101 channel not found",
                    "Set it in **👋 Onboarding → ⚙️ Settings → Getting-started channel**.",
                ),
                ephemeral=True,
            )
            return
        missing = missing_permissions(channel, interaction.guild.me)
        if missing:
            await interaction.followup.send(
                embed=embed_builder.error_embed(
                    "Missing permissions",
                    f"The bot needs **{', '.join(missing)}** in {channel.mention}.",
                ),
                ephemeral=True,
            )
            return
        message = await channel.send(
            SHOP_101_CHECKPOINT_MESSAGE, view=Shop101DoneView(), allowed_mentions=NO_MENTIONS
        )
        await interaction.followup.send(
            embed=embed_builder.success_embed(
                "Checkpoint posted",
                embed_builder.item(f"{channel.mention} · [jump to it]({message.jump_url})")
                + "\n"
                + embed_builder.item(
                    "Members who click it get the rules and the questionnaire privately."
                ),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Settings",
        style=discord.ButtonStyle.primary,
        custom_id="cgk_onboarding_hub:settings",
        emoji="⚙️",
        row=1,
    )
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        cog = _cog(interaction)
        if cog is None:
            await missing_cog(interaction, "CGK Onboarding")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        settings = await cog.settings(interaction.guild.id)
        problems = cog.setup_problems(interaction.guild, settings)
        await interaction.followup.send(
            embed=build_settings_embed(interaction.guild, settings, problems),
            view=CGKSettingsView(settings),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Stats",
        style=discord.ButtonStyle.secondary,
        custom_id="cgk_onboarding_hub:stats",
        emoji="📋",
        row=1,
    )
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await require_manage(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(embed=await build_cgk_hub_embed(interaction), ephemeral=True)


__all__ = [
    "CGKComposerMemberPickerView",
    "CGKComposerView",
    "CGKDraft",
    "CGKOnboardingHubView",
    "CGKSettingsView",
    "CGKSingleMemberSelect",
    "CGKTestMemberSelectView",
    "build_cgk_hub_embed",
    "build_composer_embed",
    "build_settings_embed",
    "open_test_channel",
]

