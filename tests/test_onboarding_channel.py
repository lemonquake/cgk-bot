"""Public onboarding publishing, privacy, persistence and error paths."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from cogs.cgk_onboarding import CategoryFull
from views.mod_panel_view import ModPanelView
from views.onboarding_channel_view import (
    AutoOnboardingView,
    OnboardingStartView,
    onboarding_channel_embed,
    open_auto_onboarding_toggle,
)
from views.creator_onboarding_view import OnboardingTicketView


class FakeTextChannel(discord.TextChannel):
    mention = None

    def __init__(self, *, permitted=True, fail=False):
        self.id = 123
        self.mention = "<#123>"
        self.permitted = permitted
        self.send = AsyncMock(return_value=SimpleNamespace(jump_url="https://discord.test/message"))
        if fail:
            self.send.side_effect = discord.Forbidden(
                SimpleNamespace(status=403, reason="no"), "no"
            )

    def permissions_for(self, member):
        return SimpleNamespace(
            view_channel=self.permitted,
            send_messages=self.permitted,
            embed_links=self.permitted,
        )


def interaction_for(cog=None, *, channel=None, admin=False, bot=False, guild=True):
    return SimpleNamespace(
        user=SimpleNamespace(id=42, bot=bot, guild_permissions=SimpleNamespace(manage_guild=admin)),
        guild=SimpleNamespace(id=1, me=object(), get_channel=lambda _: channel) if guild else None,
        client=SimpleNamespace(get_cog=lambda name: cog if name == "CGKOnboardingCog" else None),
        response=SimpleNamespace(
            defer=AsyncMock(), send_message=AsyncMock(), edit_message=AsyncMock(),
            is_done=lambda: True,
        ),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def make_cog():
    return SimpleNamespace(
        settings=AsyncMock(return_value=object()),
        setup_problems=lambda guild, settings: [],
        category=lambda guild, settings: object(),
        start_self_service=AsyncMock(return_value=(SimpleNamespace(mention="<#456>"), True)),
    )


class EntryButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_button_uses_original_private_flow_and_private_reply(self):
        cog = make_cog()
        interaction = interaction_for(cog)
        view = OnboardingStartView()
        await view.start.callback(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertIs(cog.start_self_service.call_args.args[0], interaction.user)
        self.assertIsInstance(cog.start_self_service.call_args.args[2], OnboardingTicketView)
        reply = interaction.followup.send.call_args
        self.assertIn("<#456>", reply.args[0])
        self.assertTrue(reply.kwargs["ephemeral"])

    async def test_returning_member_is_sent_to_existing_channel(self):
        cog = make_cog()
        cog.start_self_service.return_value = (SimpleNamespace(mention="<#456>"), False)
        interaction = interaction_for(cog)
        await OnboardingStartView().start.callback(interaction)
        self.assertIn("Continue your onboarding", interaction.followup.send.call_args.args[0])

    async def test_bots_and_direct_messages_cannot_start(self):
        for overrides in ({"bot": True}, {"guild": False}):
            with self.subTest(overrides=overrides):
                cog = make_cog()
                interaction = interaction_for(cog, **overrides)
                await OnboardingStartView().start.callback(interaction)
                cog.start_self_service.assert_not_awaited()
                self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_setup_problem_and_missing_module_are_reported_privately(self):
        cog = make_cog()
        cog.setup_problems = lambda guild, settings: ["Missing role"]
        for current in (cog, None):
            interaction = interaction_for(current)
            await OnboardingStartView().start.callback(interaction)
            self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])
        cog.start_self_service.assert_not_awaited()

    async def test_full_category_and_discord_errors_do_not_change_public_message(self):
        for error in (
            CategoryFull(),
            discord.Forbidden(SimpleNamespace(status=403, reason="no"), "no"),
        ):
            with self.subTest(error=type(error).__name__):
                cog = make_cog()
                cog.start_self_service.side_effect = error
                interaction = interaction_for(cog)
                await OnboardingStartView().start.callback(interaction)
                self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])
                interaction.response.edit_message.assert_not_awaited()
                interaction.edit_original_response.assert_not_awaited()

    async def test_persistent_entry_and_mod_panel_fit_discord_limits(self):
        view = OnboardingStartView()
        self.assertTrue(view.is_persistent())
        self.assertEqual(view.children[0].label, "START MY ONBOARDING")
        panel = ModPanelView()
        self.assertTrue(panel.is_persistent())
        self.assertIn("Auto Onboarding", [child.label for child in panel.children])
        for row in range(5):
            self.assertLessEqual(sum(child.row == row for child in panel.children), 5)
        self.assertIn("full access", onboarding_channel_embed().description)
        self.assertIn("Onboarding", onboarding_channel_embed().description)

    async def test_startup_registers_public_entry_for_previously_posted_messages(self):
        from main import CGKBot
        bot = CGKBot(use_presences=False)
        try:
            with patch.object(bot, "load_extension", new=AsyncMock()), patch.object(
                bot.tree, "sync", new=AsyncMock(return_value=[])
            ):
                await bot.setup_hook()
            self.assertTrue(any(isinstance(view, OnboardingStartView) for view in bot.persistent_views))
        finally:
            await bot.close()


class AutoOnboardingToggleTests(unittest.IsolatedAsyncioTestCase):
    def toggle_cog(self, enabled=False, problems=()):
        return SimpleNamespace(
            auto_enabled=AsyncMock(return_value=enabled),
            set_auto_enabled=AsyncMock(),
            settings=AsyncMock(return_value=object()),
            auto_problems=lambda guild, settings: list(problems),
        )

    async def test_only_moderators_can_open_and_use_the_switch(self):
        cog = self.toggle_cog()
        denied = interaction_for(cog, admin=False)
        await open_auto_onboarding_toggle(denied)
        denied.response.send_message.assert_not_awaited()
        self.assertFalse(await AutoOnboardingView(False).interaction_check(denied))
        allowed = interaction_for(cog, admin=True)
        await open_auto_onboarding_toggle(allowed)
        sent = allowed.response.send_message.call_args.kwargs
        self.assertTrue(sent["ephemeral"])
        self.assertIsInstance(sent["view"], AutoOnboardingView)
        self.assertIn("OFF", sent["embed"].description)

    async def test_switch_shows_current_state_and_never_offers_channel_picker(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                view = AutoOnboardingView(enabled)
                self.assertEqual(view.turn_on.disabled, enabled)
                self.assertEqual(view.turn_off.disabled, not enabled)
                self.assertFalse(any(isinstance(c, discord.ui.ChannelSelect) for c in view.children))

    async def test_turning_on_and_off_saves_the_setting(self):
        for enabled, button in ((True, "turn_on"), (False, "turn_off")):
            with self.subTest(enabled=enabled):
                cog = self.toggle_cog(not enabled, problems=["Missing role"])
                interaction = interaction_for(cog, admin=True)
                view = AutoOnboardingView(not enabled)
                await getattr(view, button).callback(interaction)
                cog.set_auto_enabled.assert_awaited_once_with(1, enabled)
                edited = interaction.response.edit_message.call_args.kwargs
                self.assertIn("ON" if enabled else "OFF", edited["embed"].description)
                self.assertEqual("Missing role" in edited["embed"].description, enabled)
                self.assertEqual(edited["view"].turn_off.disabled, not enabled)

    async def test_missing_module_is_reported(self):
        interaction = interaction_for(None, admin=True)
        await open_auto_onboarding_toggle(interaction)
        interaction.response.send_message.assert_not_awaited()
        self.assertIn("unavailable", interaction.followup.send.call_args.kwargs["embed"].title)
