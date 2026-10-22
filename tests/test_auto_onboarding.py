"""
Auto onboarding: a member who joins gets the onboarding role, loses sight of
the hidden channel and gets a private channel; finishing undoes both.
"""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import discord

import cogs.cgk_onboarding as cgk
from tests.test_cgk_onboarding import CGKTestCase, FakeGuild, FakeMember, FakeRole


class FakeHiddenChannel:
    def __init__(self, manage=True):
        self.id = cgk.AUTO_HIDDEN_CHANNEL_ID
        self.mention = f"<#{self.id}>"
        self.member_overwrites = {}
        self._manage = manage

    def permissions_for(self, member):
        return SimpleNamespace(manage_roles=self._manage)

    def overwrites_for(self, member):
        return self.member_overwrites.get(member.id, discord.PermissionOverwrite())

    async def set_permissions(self, member, *, overwrite=discord.utils.MISSING, reason=None, **perms):
        if overwrite is None:
            self.member_overwrites.pop(member.id, None)
        else:
            self.member_overwrites[member.id] = discord.PermissionOverwrite(**perms)


def auto_guild():
    guild = FakeGuild()
    guild.auto_role = FakeRole(cgk.AUTO_ONBOARDING_ROLE_ID, 3)
    guild.roles.append(guild.auto_role)
    guild.hidden = FakeHiddenChannel()
    guild.channels[guild.hidden.id] = guild.hidden
    return guild


class AutoOnboardingTests(CGKTestCase):
    async def test_switch_is_off_until_turned_on(self):
        self.assertFalse(await self.cog.auto_enabled(1))
        await self.cog.set_auto_enabled(1, True)
        self.assertTrue(await self.cog.auto_enabled(1))
        await self.cog.set_auto_enabled(1, False)
        self.assertFalse(await self.cog.auto_enabled(1))

    async def test_join_while_off_does_nothing(self):
        guild = auto_guild()
        member = FakeMember(guild, 42, "lemon")
        await self.cog.on_member_join(member)
        self.assertEqual(member.added, [])
        self.assertEqual(guild.created, [])
        self.assertEqual(guild.hidden.member_overwrites, {})

    async def test_join_while_on_gives_role_hides_channel_and_opens_private_channel(self):
        await self.cog.set_auto_enabled(1, True)
        guild = auto_guild()
        member = FakeMember(guild, 42, "lemon")
        await self.cog.on_member_join(member)
        self.assertEqual(member.added, [guild.auto_role])
        self.assertFalse(guild.hidden.overwrites_for(member).view_channel)
        self.assertEqual(len(guild.created), 1)
        channel = guild.created[0]
        self.assertEqual(channel.name, "lemon-onboarding")
        self.assertIn(member.mention, channel.sent[0]["content"])
        # Scans skip them, but they are never part of a clearable tagged group.
        self.assertEqual(await self.cog.tagged_ids(1), {42})
        self.assertIsNone(await self.cog.last_group(1))

    async def test_bots_are_never_onboarded(self):
        await self.cog.set_auto_enabled(1, True)
        guild = auto_guild()
        bot = FakeMember(guild, 42, "helper")
        bot.bot = True
        await self.cog.on_member_join(bot)
        self.assertEqual(guild.created, [])

    async def test_rejoining_member_reuses_existing_channel(self):
        await self.cog.set_auto_enabled(1, True)
        guild = auto_guild()
        await self.cog.on_member_join(FakeMember(guild, 42, "lemon"))
        await self.cog.on_member_join(FakeMember(guild, 42, "lemon"))
        self.assertEqual(len(guild.created), 1)
        self.assertEqual(len(guild.created[0].sent), 1)

    async def test_role_failure_still_opens_channel(self):
        await self.cog.set_auto_enabled(1, True)
        guild = auto_guild()
        member = FakeMember(guild, 42, "lemon")
        member.fail_add = True
        await self.cog.on_member_join(member)
        self.assertEqual(len(guild.created), 1)

    async def test_finishing_grants_access_and_removes_onboarding_roles_and_hiding(self):
        await self.cog.set_auto_enabled(1, True)
        guild = auto_guild()
        legacy = FakeRole(cgk.ONBOARDING_PENDING_ROLE_ID, 3)
        guild.roles.append(legacy)
        member = FakeMember(guild, 42, "lemon", roles=[legacy])
        await self.cog.on_member_join(member)
        with patch.object(discord, "Member", FakeMember):
            self.assertTrue(await self.cog.complete(member))
        self.assertIn(guild.access_role, member.roles)
        self.assertNotIn(guild.auto_role, member.roles)
        self.assertNotIn(legacy, member.roles)
        self.assertEqual(guild.hidden.member_overwrites, {})

    async def test_leaving_before_finishing_clears_the_hidden_override(self):
        await self.cog.set_auto_enabled(1, True)
        guild = auto_guild()
        member = FakeMember(guild, 42, "lemon")
        await self.cog.on_member_join(member)
        await self.cog.on_member_remove(member)
        self.assertEqual(guild.hidden.member_overwrites, {})

    async def test_onboarding_role_cannot_be_the_access_role(self):
        guild = auto_guild()
        await self.cog.set_value(1, "role", cgk.AUTO_ONBOARDING_ROLE_ID)
        member = FakeMember(guild, 42, "lemon", roles=[guild.auto_role])
        self.assertFalse(await self.cog.complete(member))
        self.assertIn(guild.auto_role, member.roles)

    async def test_auto_problems_report_missing_role_and_channel(self):
        guild = FakeGuild()
        settings = await self.cog.settings(1)
        problems = "\n".join(self.cog.auto_problems(guild, settings))
        self.assertIn(str(cgk.AUTO_ONBOARDING_ROLE_ID), problems)
        self.assertIn(str(cgk.AUTO_HIDDEN_CHANNEL_ID), problems)
        guild = auto_guild()
        guild.hidden._manage = False
        problems = "\n".join(self.cog.auto_problems(guild, settings))
        self.assertIn("Manage Permissions", problems)
        self.assertNotIn(str(cgk.AUTO_ONBOARDING_ROLE_ID), problems)


if __name__ == "__main__":
    unittest.main()
