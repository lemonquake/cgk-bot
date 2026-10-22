"""
Unit tests for CGK Onboarding (private per-member onboarding channels).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import asyncio
import unittest
from unittest.mock import AsyncMock

import discord

import cogs.cgk_onboarding as cgk
from cogs.cgk_onboarding import (
    CATEGORY_LIMIT,
    SETTING_KEYS,
    TICKET_INTRO,
    TOPIC_TEMPLATE,
    CGKOnboardingCog,
    CGKSettings,
    TaggedGroup,
    can_close,
    channel_name,
    owner_from_topic,
    ticket_overwrites,
)
from cogs.creator_onboarding import WELCOME_MESSAGE
from cogs.onboarding import DayGroup
from core.database import CommunityDatabase
from views.cgk_onboarding_view import (
    CGKComposerView,
    CGKDraft,
    CGKOnboardingHubView,
    build_composer_embed,
)
from views.creator_onboarding_view import CloseConfirmView, OnboardingTicketView, ask_to_close

GUILD_ID = 1
ROLE_ID = 700
CATEGORY_ID = 800


class FakeRole:
    def __init__(self, role_id, position, permissions=None, *, default=False, managed=False):
        self.id = role_id
        self.position = position
        self.permissions = permissions or discord.Permissions.none()
        self.managed = managed
        self._default = default
        self.mention = f"<@&{role_id}>"

    def is_default(self):
        return self._default

    def __ge__(self, other):
        return self.position >= other.position

    def __hash__(self):
        return self.id


class FakeChannel:
    def __init__(self, channel_id, name="", topic=None, category=None, overwrites=None):
        self.id = channel_id
        self.name = name
        self.topic = topic
        self.category = category
        self.overwrites = overwrites or {}
        self.mention = f"<#{channel_id}>"
        self.sent = []
        self.guild = SimpleNamespace(id=GUILD_ID)

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(jump_url=f"https://discord.test/{self.id}")


class FakeCategory(discord.CategoryChannel):
    """A real CategoryChannel subclass so isinstance checks pass."""

    channels = None  # shadows the read-only property

    def __init__(self, category_id=CATEGORY_ID, count=0, manage=True):  # noqa: D107
        self.id = category_id
        self.name = "Onboarding"
        self.channels = [object()] * count
        self._manage = manage

    def permissions_for(self, member):
        return SimpleNamespace(manage_channels=self._manage)


class FakeTextChannel(discord.TextChannel):
    """A real TextChannel subclass so isinstance checks pass."""

    category = overwrites = mention = None  # shadow the read-only properties

    def __init__(self, channel_id, name="", topic=None, category=None, overwrites=None):  # noqa: D107
        self.id = channel_id
        self.name = name
        self.topic = topic
        self.category = category
        self.overwrites = overwrites or {}
        self.mention = f"<#{channel_id}>"
        self.guild = SimpleNamespace(id=GUILD_ID)
        self.sent = []
        self.deleted = None

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(jump_url=f"https://discord.test/{self.id}")

    async def delete(self, *, reason=None):
        self.deleted = reason


class FakeMember:
    def __init__(self, guild, member_id, name, *, days_ago=0, roles=None):
        self.id = member_id
        self.name = name
        self.display_name = name.title()
        self.mention = f"<@{member_id}>"
        self.bot = False
        self.guild = guild
        self.roles = list(roles or [])
        self.joined_at = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
        self.added = []
        self.fail_add = False
        self.removed = []
        self.fail_remove = False

    async def remove_roles(self, role, reason=None):
        if self.fail_remove:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="no"), "no")
        self.removed.append(role)
        self.roles.remove(role)

    async def add_roles(self, role, reason=None):
        if self.fail_add:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="no"), "no")
        self.added.append(role)
        self.roles.append(role)

    def __str__(self):
        return self.name


class FakeGuild:
    def __init__(self, *, category=None, bot_position=10, manage_roles=True):
        self.id = GUILD_ID
        self.chunked = True
        self.default_role = FakeRole(GUILD_ID, 0, default=True)
        self.access_role = FakeRole(ROLE_ID, 5)
        self.mod_role = FakeRole(600, 4, discord.Permissions(manage_messages=True))
        self.plain_role = FakeRole(601, 3)
        self.bot_role = FakeRole(602, bot_position, discord.Permissions(administrator=True), managed=True)
        self.roles = [self.default_role, self.access_role, self.mod_role, self.plain_role, self.bot_role]
        self.me = discord.Object(999)
        self.me.top_role = self.bot_role
        self.me.guild_permissions = SimpleNamespace(manage_roles=manage_roles)
        self.category_channel = category if category is not None else FakeCategory()
        self.channels = {CATEGORY_ID: self.category_channel}
        self.members = []
        self.created = []

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)

    async def create_text_channel(self, name, *, category, overwrites, topic, reason):
        channel = FakeTextChannel(
            5000 + len(self.created), name, topic=topic, category=category, overwrites=overwrites
        )
        self.created.append(channel)
        self.channels[channel.id] = channel
        return channel


def view_factory():
    return "VIEW"


class HelperTests(unittest.TestCase):
    def test_channel_names(self):
        self.assertEqual(channel_name(SimpleNamespace(name="lemon", id=1)), "lemon-onboarding")
        self.assertEqual(channel_name(SimpleNamespace(name="Lemon.PC", id=1)), "lemon-pc-onboarding")
        self.assertEqual(channel_name(SimpleNamespace(name="__", id=7)), "member-7-onboarding")

    def test_owner_from_topic(self):
        topic = TOPIC_TEMPLATE.format(member="lemon", member_id=123456789012345678)
        self.assertEqual(owner_from_topic(topic), 123456789012345678)
        self.assertIsNone(owner_from_topic("General chat"))
        self.assertIsNone(owner_from_topic(None))

    def test_only_designated_moderator_role_can_close(self):
        channel = SimpleNamespace(permissions_for=lambda member: discord.Permissions.all())
        owner = SimpleNamespace(id=42, roles=[])
        moderator = SimpleNamespace(id=7, roles=[SimpleNamespace(id=1542915539872125049)])
        wrong_role = SimpleNamespace(id=8, roles=[SimpleNamespace(id=1549415196123074581)])
        self.assertEqual(cgk.ONBOARDING_MODERATOR_ROLE_ID, 1542915539872125049)
        self.assertFalse(can_close(owner, channel, 42))
        self.assertFalse(can_close(SimpleNamespace(id=7), channel, 42))
        self.assertFalse(can_close(wrong_role, channel, 42))
        self.assertTrue(can_close(moderator, channel, 42))
        self.assertFalse(can_close(moderator, channel, None))
        owner.roles = moderator.roles
        self.assertTrue(can_close(owner, channel, 42))  # authorized by role, not ownership

    def test_only_member_staff_and_bot_can_see_the_channel(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        overwrites = ticket_overwrites(guild, member)
        self.assertIs(overwrites[guild.default_role].view_channel, False)
        self.assertIs(overwrites[member].view_channel, True)
        self.assertIs(overwrites[member].send_messages, True)
        self.assertIs(overwrites[guild.mod_role].view_channel, True)
        self.assertIs(overwrites[guild.me].view_channel, True)
        self.assertNotIn(guild.plain_role, overwrites)
        self.assertNotIn(guild.access_role, overwrites)
        self.assertNotIn(guild.bot_role, overwrites)  # managed roles are skipped


class CGKTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.db = CommunityDatabase(Path(self.tmp.name) / "community.sqlite3")
        await self.db.initialize()
        self.cog = CGKOnboardingCog.__new__(CGKOnboardingCog)
        self.cog.bot = None
        self.cog.db = self.db
        self.cog._self_service_lock = asyncio.Lock()
        self._pace = cgk.CREATE_PACE_SECONDS
        cgk.CREATE_PACE_SECONDS = 0
        self._defaults = dict(cgk.ENV_DEFAULTS)
        cgk.ENV_DEFAULTS.update(category=CATEGORY_ID, role=ROLE_ID)

    async def asyncTearDown(self):
        cgk.CREATE_PACE_SECONDS = self._pace
        cgk.ENV_DEFAULTS.clear()
        cgk.ENV_DEFAULTS.update(self._defaults)
        await self.db.close()
        self.tmp.cleanup()

    async def deliver(self, guild, members, batch_id):
        return await self.cog.deliver(
            guild=guild,
            members=members,
            moderator=SimpleNamespace(id=9),
            batch_id=batch_id,
            view_factory=view_factory,
        )


class SettingsTests(CGKTestCase):
    async def test_defaults_then_saved_values(self):
        settings = await self.cog.settings(GUILD_ID)
        self.assertEqual((settings.category_id, settings.role_id), (CATEGORY_ID, ROLE_ID))
        self.assertEqual(settings.sources, {"category": "env", "role": "env"})
        await self.cog.set_value(GUILD_ID, "role", 701)
        settings = await self.cog.settings(GUILD_ID)
        self.assertEqual((settings.role_id, settings.sources["role"]), (701, "saved"))
        self.assertEqual(await self.db.get_setting(GUILD_ID, SETTING_KEYS["role"]), "701")

    async def test_setup_problems(self):
        settings = await self.cog.settings(GUILD_ID)
        self.assertEqual(self.cog.setup_problems(FakeGuild(), settings), [])
        broken = FakeGuild(bot_position=2, manage_roles=False)
        broken.channels.clear()
        problems = " ".join(self.cog.setup_problems(broken, settings))
        self.assertIn("category", problems)
        self.assertIn("Manage Roles", problems)
        self.assertIn("above", problems)
        no_manage = FakeGuild(category=FakeCategory(manage=False))
        self.assertIn("Manage Channels", " ".join(self.cog.setup_problems(no_manage, settings)))


class TicketTests(CGKTestCase):
    async def test_open_creates_private_channel_and_tags_member(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        result = await self.deliver(guild, [member], batch_id=1)
        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.member_ids, [42])
        channel = guild.created[0]
        self.assertEqual(channel.name, "lemon-onboarding")
        self.assertIs(channel.category, guild.category_channel)
        self.assertEqual(owner_from_topic(channel.topic), 42)
        sent = channel.sent[0]
        self.assertTrue(sent["content"].startswith(TICKET_INTRO.format(mention="<@42>")))
        self.assertTrue(sent["content"].endswith(WELCOME_MESSAGE))
        self.assertIn("unlock all of the server's channels", sent["content"])
        self.assertIn("Got a question", sent["content"])
        self.assertEqual(sent["view"], "VIEW")
        self.assertEqual(await self.cog.owner_of(channel), 42)

    async def test_owner_lookup_falls_back_to_the_database(self):
        guild = FakeGuild()
        await self.deliver(guild, [FakeMember(guild, 42, "lemon")], batch_id=1)
        channel = guild.created[0]
        channel.topic = "renamed by a moderator"
        self.assertEqual(await self.cog.owner_of(channel), 42)
        self.assertIsNone(await self.cog.owner_of(FakeChannel(1234)))

    async def test_clear_last_group_and_retag_reuses_channel(self):
        guild = FakeGuild()
        first = [FakeMember(guild, 1, "ann"), FakeMember(guild, 2, "bob")]
        second = [FakeMember(guild, 3, "cat")]
        await self.deliver(guild, first, batch_id=100)
        await asyncio.sleep(0.01)
        await self.deliver(guild, second, batch_id=200)
        self.assertEqual(await self.cog.tagged_ids(GUILD_ID), {1, 2, 3})

        group = await self.cog.last_group(GUILD_ID)
        self.assertEqual((group.batch_id, group.count), (200, 1))
        self.assertEqual(await self.cog.clear_last_group(GUILD_ID), 1)
        self.assertEqual(await self.cog.tagged_ids(GUILD_ID), {1, 2})
        self.assertEqual((await self.cog.last_group(GUILD_ID)).batch_id, 100)

        again = await self.deliver(guild, second, batch_id=300)
        self.assertEqual((len(again.created), len(again.reused)), (0, 1))
        self.assertEqual(len(guild.created), 3)
        self.assertEqual(len(guild.created[2].sent), 2)  # re-tagged in the same channel

    async def test_test_run_does_not_tag(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        channel, created = await self.cog.open_ticket(
            member, guild.category_channel, "VIEW", batch_id=None, tagged_by=None
        )
        self.assertTrue(created)
        self.assertEqual(await self.cog.tagged_ids(GUILD_ID), set())
        self.assertIsNone(await self.cog.last_group(GUILD_ID))
        self.assertEqual(await self.cog.owner_of(channel), 42)

    async def test_full_category_is_reported(self):
        guild = FakeGuild(category=FakeCategory(count=CATEGORY_LIMIT))
        result = await self.deliver(guild, [FakeMember(guild, 1, "ann")], batch_id=1)
        self.assertEqual(result.opened, 0)
        self.assertIn("category is full", result.failed[0][1])
        self.assertEqual(await self.cog.tagged_ids(GUILD_ID), set())

    async def test_pending_skips_tagged_and_members_with_access(self):
        guild = FakeGuild()
        onboarding = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
        guild.roles.append(onboarding)
        fresh = FakeMember(guild, 1, "ann", roles=[onboarding])
        has_access = FakeMember(guild, 2, "bob", roles=[onboarding, guild.access_role])
        tagged = FakeMember(guild, 3, "cat", roles=[onboarding])
        old = FakeMember(guild, 4, "dan", days_ago=400, roles=[onboarding])
        no_onboarding_role = FakeMember(guild, 5, "eve")
        guild.members = [fresh, has_access, tagged, old, no_onboarding_role]
        await self.deliver(guild, [tagged], batch_id=1)
        self.assertEqual([m.id for m in await self.cog.pending_members(guild)], [1])


class CompletionTests(CGKTestCase):
    async def test_form_only_updates_roles_after_valid_answers_are_saved(self):
        from views.creator_onboarding_view import CreatorQuestionnaireModal

        for index, (valid, save_error, saved) in enumerate([
            (True, False, True),
            (True, False, False),  # Existing saved answers can retry role updates.
            (False, False, True),
            (True, True, True),
        ]):
            with self.subTest(valid=valid, save_error=save_error, saved=saved):
                guild = FakeGuild()
                pending = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
                guild.roles.append(pending)
                member = FakeMember(guild, 42 + index, "lemon", roles=[pending])
                questionnaire = SimpleNamespace(save_answers=AsyncMock(return_value=saved))
                if save_error:
                    questionnaire.save_answers.side_effect = RuntimeError("database unavailable")
                cogs = {"CGKOnboardingCog": self.cog, "QuestionnaireCog": questionnaire}
                interaction = SimpleNamespace(
                    user=member, guild=guild, channel=None,
                    client=SimpleNamespace(get_cog=cogs.get),
                    response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
                    followup=SimpleNamespace(send=AsyncMock()),
                )
                modal = CreatorQuestionnaireModal(member)
                values = dict(
                    tt_handle="@lemon", email="lemon@example.com" if valid else "invalid",
                    phone="+1 555 123 4567", gmv="USD 0", birthday="",
                )
                modal.inputs = {key: SimpleNamespace(value=value) for key, value in values.items()}
                with unittest.mock.patch.object(discord, "Member", FakeMember):
                    await modal.on_submit(interaction)
                completed = valid and not save_error
                self.assertEqual(member.removed, [pending] if completed else [])
                self.assertEqual(member.added, [guild.access_role] if completed else [])
                if not valid:
                    questionnaire.save_answers.assert_not_awaited()

    async def test_completion_removes_only_this_servers_onboarding_role(self):
        self.assertEqual(cgk.ONBOARDING_PENDING_ROLE_ID, 1559649034598227968)
        guild = FakeGuild()
        pending = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
        other = FakeRole(1559650120621105182, 3)
        guild.roles.extend([pending, other])
        member = FakeMember(guild, 42, "lemon", roles=[pending, other])
        self.assertTrue(await self.cog.complete(member))
        self.assertEqual(member.added, [guild.access_role])
        self.assertEqual(member.removed, [pending])
        self.assertIn(other, member.roles)
        self.assertTrue(await self.cog.complete(member))
        self.assertEqual(member.removed, [pending])
        self.assertEqual(member.added, [guild.access_role])

    async def test_existing_access_role_still_removes_onboarding_role(self):
        guild = FakeGuild()
        pending = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
        guild.roles.append(pending)
        member = FakeMember(guild, 42, "lemon", roles=[pending, guild.access_role])
        self.assertTrue(await self.cog.complete(member))
        self.assertEqual(member.added, [])
        self.assertEqual(member.removed, [pending])

    async def test_access_failure_preserves_onboarding_role_and_completion(self):
        guild = FakeGuild()
        pending = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
        guild.roles.append(pending)
        member = FakeMember(guild, 42, "lemon", roles=[pending])
        member.fail_add = True
        self.assertFalse(await self.cog.complete(member))
        self.assertEqual(member.removed, [])
        row = await self.db.fetchone(
            "SELECT completed_at FROM cgk_onboarding_members WHERE user_id=? AND guild_id=?",
            (42, GUILD_ID),
        )
        self.assertIsNone(row)

    async def test_removal_failure_can_retry_without_granting_access_twice(self):
        guild = FakeGuild()
        pending = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
        guild.roles.append(pending)
        member = FakeMember(guild, 42, "lemon", roles=[pending])
        member.fail_remove = True
        self.assertFalse(await self.cog.complete(member))
        row = await self.db.fetchone(
            "SELECT completed_at FROM cgk_onboarding_members WHERE user_id=? AND guild_id=?",
            (42, GUILD_ID),
        )
        self.assertIsNone(row)
        member.fail_remove = False
        self.assertTrue(await self.cog.complete(member))
        self.assertEqual(member.added, [guild.access_role])
        self.assertEqual(member.removed, [pending])

    async def test_pending_role_cannot_be_configured_as_access_role(self):
        guild = FakeGuild()
        pending = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
        guild.roles.append(pending)
        await self.cog.set_value(GUILD_ID, "role", pending.id)
        member = FakeMember(guild, 42, "lemon", roles=[pending])
        self.assertFalse(await self.cog.complete(member))
        self.assertIn(pending, member.roles)

    async def test_self_service_clicks_create_one_channel_and_preserve_progress(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        results = await asyncio.gather(*[
            self.cog.start_self_service(member, guild.category_channel, view_factory())
            for _ in range(3)
        ])
        self.assertEqual(len(guild.created), 1)
        self.assertEqual([created for _, created in results], [True, False, False])
        self.assertEqual(len(guild.created[0].sent), 1)
        self.assertEqual(member.added, [])
        row = await self.db.fetchone(
            "SELECT completed_at, batch_id, tagged_by FROM cgk_onboarding_members WHERE user_id=? AND guild_id=?",
            (42, GUILD_ID),
        )
        self.assertIsNone(row["completed_at"])
        self.assertIsNone(row["batch_id"])
        self.assertIsNone(row["tagged_by"])

    async def test_grants_role_and_counts_completion(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        guild.members = [member]
        await self.deliver(guild, [member], batch_id=1)
        self.assertTrue(await self.cog.complete(member))
        self.assertEqual(member.added, [guild.access_role])
        self.assertTrue(await self.cog.complete(member))  # already has it: no second add
        self.assertEqual(len(member.added), 1)
        stats = await self.cog.stats(guild)
        self.assertEqual((stats["channels"], stats["completed"], stats["pending"]), (1, 1, 0))

    async def test_role_failure_returns_false(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        member.fail_add = True
        self.assertFalse(await self.cog.complete(member))
        await self.cog.set_value(GUILD_ID, "role", 12345)  # a role that does not exist
        member.fail_add = False
        self.assertFalse(await self.cog.complete(member))


class CloseTests(CGKTestCase):
    async def test_close_deletes_and_next_tag_opens_a_fresh_channel(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        await self.deliver(guild, [member], batch_id=1)
        channel = guild.created[0]
        moderator = FakeMember(guild, 7, "moderator", roles=[FakeRole(1542915539872125049, 4)])
        await self.cog.close_ticket(channel, closed_by=moderator)
        self.assertIn("closed by moderator", channel.deleted)
        self.assertEqual((await self.cog.stats(guild))["channels"], 0)
        self.assertEqual(await self.cog.owner_of(channel), 42)  # topic still names them
        await self.cog.clear_last_group(GUILD_ID)
        await self.deliver(guild, [member], batch_id=2)
        self.assertEqual(len(guild.created), 2)

    async def test_member_cannot_delete_own_channel(self):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        await self.deliver(guild, [member], batch_id=1)
        channel = guild.created[0]
        with self.assertRaises(PermissionError):
            await self.cog.close_ticket(channel, closed_by=member)
        self.assertIsNone(channel.deleted)
        self.assertEqual((await self.cog.stats(guild))["channels"], 1)

    async def make_close_interaction(self, *, moderator=False):
        guild = FakeGuild()
        member = FakeMember(guild, 42, "lemon")
        await self.deliver(guild, [member], batch_id=1)
        user = (
            FakeMember(guild, 7, "moderator", roles=[FakeRole(1542915539872125049, 4)])
            if moderator else member
        )
        return SimpleNamespace(
            guild=guild, channel=guild.created[0], user=user,
            client=SimpleNamespace(get_cog=lambda name: self.cog),
            response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

    async def test_member_close_button_is_denied(self):
        interaction = await self.make_close_interaction()
        await ask_to_close(interaction)
        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("Only moderators", args[0])
        self.assertIn("1542915539872125049", args[0])
        self.assertTrue(kwargs["ephemeral"])
        self.assertNotIn("view", kwargs)
        self.assertIsNone(interaction.channel.deleted)

    async def test_moderator_button_and_confirmation_delete_channel(self):
        interaction = await self.make_close_interaction(moderator=True)
        await ask_to_close(interaction)
        confirmation = interaction.response.send_message.call_args.kwargs["view"]
        self.assertIsInstance(confirmation, CloseConfirmView)
        await confirmation.confirm.callback(interaction)
        self.assertIn("closed by moderator", interaction.channel.deleted)

    async def test_confirmation_rechecks_role_after_it_is_removed(self):
        interaction = await self.make_close_interaction(moderator=True)
        await ask_to_close(interaction)
        confirmation = interaction.response.send_message.call_args.kwargs["view"]
        interaction.user.roles.clear()
        await confirmation.confirm.callback(interaction)
        self.assertIsNone(interaction.channel.deleted)
        interaction.response.edit_message.assert_awaited_once()
        self.assertIn(
            "Not allowed", interaction.response.edit_message.call_args.kwargs["embed"].title
        )

    async def test_member_cannot_use_confirmation_directly(self):
        interaction = await self.make_close_interaction()
        confirmation = CloseConfirmView(interaction.channel.id)
        await confirmation.confirm.callback(interaction)
        self.assertIsNone(interaction.channel.deleted)
        self.assertIn(
            "Not allowed", interaction.response.edit_message.call_args.kwargs["embed"].title
        )

    async def test_channel_deleted_by_hand_is_forgotten(self):
        guild = FakeGuild()
        await self.deliver(guild, [FakeMember(guild, 42, "lemon")], batch_id=1)
        await self.cog.on_guild_channel_delete(guild.created[0])
        self.assertEqual((await self.cog.stats(guild))["channels"], 0)


class ComposerTests(unittest.TestCase):
    def make_draft(self, *, groups=True, problems=(), last=None):
        members = [SimpleNamespace(id=1, display_name="Ann", joined_at=datetime.now(timezone.utc))]
        return CGKDraft(
            user_id=7,
            groups=[DayGroup("d0", "Joined today", "", members)] if groups else [],
            settings=CGKSettings(CATEGORY_ID, ROLE_ID, {"category": "env", "role": "env"}),
            last_group=last,
            problems=list(problems),
        )

    def test_ready_to_send(self):
        async def check():
            view = CGKComposerView(self.make_draft(last=TaggedGroup(5, 3, 1_700_000_000)))
            self.assertEqual(view.send.label, "Open 1 onboarding channel")
            self.assertFalse(view.send.disabled)
            self.assertFalse(view.clear_and_rescan.disabled)

        asyncio.run(check())

    def test_blocked_by_setup_problems_and_nothing_to_clear(self):
        async def check():
            view = CGKComposerView(self.make_draft(problems=["Manage Roles"]))
            self.assertTrue(view.send.disabled)
            self.assertTrue(view.clear_and_rescan.disabled)

        asyncio.run(check())

    def test_everyone_tagged_still_offers_clear_and_rescan(self):
        async def check():
            draft = self.make_draft(groups=False, last=TaggedGroup(5, 3, 1_700_000_000))
            view = CGKComposerView(draft)
            self.assertTrue(view.send.disabled)
            self.assertFalse(view.clear_and_rescan.disabled)
            self.assertFalse(any(isinstance(item, discord.ui.Select) for item in view.children))
            guild = SimpleNamespace(get_channel=lambda _: SimpleNamespace(name="Onboarding"))
            embed = build_composer_embed(draft, guild)
            self.assertIn("**3** members", embed.description)
            self.assertIn("<@&700>", embed.description)

        asyncio.run(check())

    def test_ticket_view_has_answers_and_close(self):
        async def check():
            view = OnboardingTicketView()
            self.assertTrue(view.is_persistent())
            self.assertEqual(
                {child.custom_id for child in view.children},
                {
                    "cgk_creator_onboarding:yes",
                    "cgk_creator_onboarding:no",
                    "cgk_onboarding:close",
                },
            )

        asyncio.run(check())

    def test_hub_is_persistent(self):
        async def check():
            hub = CGKOnboardingHubView()
            self.assertTrue(hub.is_persistent())
            self.assertEqual(
                {child.custom_id for child in hub.children},
                {
                    "cgk_onboarding_hub:scan",
                    "cgk_onboarding_hub:single_member",
                    "cgk_onboarding_hub:test",
                    "cgk_onboarding_hub:test_member",
                    "cgk_onboarding_hub:checkpoint",
                    "cgk_onboarding_hub:settings",
                    "cgk_onboarding_hub:stats",
                },
            )

        asyncio.run(check())

    def test_single_member_selection_in_draft(self):
        member1 = SimpleNamespace(id=1, display_name="Ann", joined_at=datetime.now(timezone.utc))
        member2 = SimpleNamespace(id=2, display_name="Bob", joined_at=datetime.now(timezone.utc))
        draft = CGKDraft(
            user_id=7,
            groups=[DayGroup("d0", "Joined today", "", [member1, member2])],
            settings=CGKSettings(CATEGORY_ID, ROLE_ID, {"category": "env", "role": "env"}),
            last_group=None,
            problems=[],
        )
        self.assertEqual(len(draft.selected_members), 2)
        draft.select_single_member(2)
        self.assertEqual(len(draft.selected_members), 1)
        self.assertEqual(draft.selected_members[0].id, 2)

        view = CGKComposerView(draft)
        self.assertEqual(view.send.label, "Open onboarding for Bob")

        # Switching back to day selection clears single member mode
        draft.apply_selection({"all"})
        self.assertIsNone(draft.selected_member_id)
        self.assertEqual(len(draft.selected_members), 2)

    def test_test_member_select_view(self):
        from views.cgk_onboarding_view import CGKTestMemberSelectView

        view = CGKTestMemberSelectView()
        self.assertEqual(len(view.children), 2)
        self.assertTrue(any(isinstance(c, discord.ui.UserSelect) for c in view.children))
        self.assertTrue(any(isinstance(c, discord.ui.Button) for c in view.children))


if __name__ == "__main__":
    unittest.main()

