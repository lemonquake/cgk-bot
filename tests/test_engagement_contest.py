"""
Unit tests for the Engagement Contest feature.
"""

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from cogs.engagement_contest import (
    ContestEvent,
    ContestStore,
    contains_tiktok_link,
    is_contest_channel,
    is_excluded_member,
)
from config import (
    CONTEST_CHANNEL_IDS,
    CONTEST_EXCLUDED_ROLE_IDS,
    CONTEST_POINTS_MESSAGE,
    CONTEST_POINTS_REACTION,
    CONTEST_POINTS_TIKTOK,
    REPORT_TIMEZONE,
)
from views.engagement_contest_view import (
    _parse_custom_contest_range,
    _report_timezone,
    get_today_range,
)


class TestTikTokLinkDetection(unittest.TestCase):
    def test_standard_tiktok_urls(self):
        self.assertTrue(
            contains_tiktok_link("Check this out https://www.tiktok.com/@user/video/1234567890123")
        )
        self.assertTrue(
            contains_tiktok_link("https://tiktok.com/@brand/video/9876543210")
        )

    def test_short_and_mobile_urls(self):
        self.assertTrue(contains_tiktok_link("https://vt.tiktok.com/ZS2xYAbc/"))
        self.assertTrue(contains_tiktok_link("https://vm.tiktok.com/ZM8abc/"))
        self.assertTrue(contains_tiktok_link("http://m.tiktok.com/v/12345.html"))

    def test_urls_with_query_parameters(self):
        self.assertTrue(
            contains_tiktok_link(
                "My submission: https://www.tiktok.com/@cgk/video/12345?is_from_webapp=1&sender_device=pc"
            )
        )

    def test_non_tiktok_urls(self):
        self.assertFalse(contains_tiktok_link("https://youtube.com/watch?v=123"))
        self.assertFalse(contains_tiktok_link("https://instagram.com/p/123"))
        self.assertFalse(contains_tiktok_link("https://not-tiktok.com/video"))
        self.assertFalse(contains_tiktok_link("plain message without any links"))
        self.assertFalse(contains_tiktok_link(None))

    def test_embed_urls(self):
        mock_embed = MagicMock()
        mock_embed.url = "https://www.tiktok.com/@user/video/123"
        mock_embed.description = None
        self.assertTrue(contains_tiktok_link("", embeds=[mock_embed]))

        mock_embed_desc = MagicMock()
        mock_embed_desc.url = None
        mock_embed_desc.description = "Link here: https://vt.tiktok.com/ABC/"
        self.assertTrue(contains_tiktok_link(None, embeds=[mock_embed_desc]))


class TestContestChannelFilter(unittest.TestCase):
    def test_contest_channels(self):
        for channel_id in CONTEST_CHANNEL_IDS:
            mock_channel = MagicMock()
            mock_channel.id = channel_id
            self.assertTrue(is_contest_channel(mock_channel))

    def test_thread_in_contest_channel(self):
        parent_id = next(iter(CONTEST_CHANNEL_IDS))
        mock_thread = MagicMock()
        mock_thread.id = 999999999999
        mock_thread.parent_id = parent_id
        self.assertTrue(is_contest_channel(mock_thread))

    def test_non_contest_channel(self):
        mock_channel = MagicMock()
        mock_channel.id = 111111111111
        mock_channel.parent_id = None
        self.assertFalse(is_contest_channel(mock_channel))
        self.assertFalse(is_contest_channel(None))


class TestExcludedMemberFilter(unittest.TestCase):
    def test_bot_excluded(self):
        mock_member = MagicMock()
        mock_member.bot = True
        mock_member.roles = []
        self.assertTrue(is_excluded_member(mock_member))

    def test_excluded_roles(self):
        for role_id in CONTEST_EXCLUDED_ROLE_IDS:
            mock_member = MagicMock()
            mock_member.bot = False
            mock_role = MagicMock()
            mock_role.id = role_id
            mock_member.roles = [mock_role]
            self.assertTrue(is_excluded_member(mock_member))

    def test_regular_qualifying_member(self):
        mock_member = MagicMock()
        mock_member.bot = False
        regular_role = MagicMock()
        regular_role.id = 123456789
        mock_member.roles = [regular_role]
        self.assertFalse(is_excluded_member(mock_member))


class TestContestStoreAndScoring(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_contest.sqlite3"
        self.store = ContestStore(self.db_path)
        await self.store.initialize()

    async def asyncTearDown(self):
        await self.store.close()
        self.temp_dir.cleanup()

    async def test_record_and_aggregate_scoring(self):
        guild_id = 1000
        channel_id = next(iter(CONTEST_CHANNEL_IDS))
        now = datetime.now(timezone.utc)

        events = [
            # User 1: 2 messages (2 * 3 = 6 pts), 1 TikTok (5 pts), 3 reactions (3 * 1 = 3 pts) -> 14 pts
            ContestEvent(guild_id, 101, "Alice", channel_id, "message", now - timedelta(hours=2), "msg:1", CONTEST_POINTS_MESSAGE),
            ContestEvent(guild_id, 101, "Alice", channel_id, "message", now - timedelta(hours=1), "msg:2", CONTEST_POINTS_MESSAGE),
            ContestEvent(guild_id, 101, "Alice", channel_id, "tiktok", now - timedelta(minutes=45), "msg:3", CONTEST_POINTS_TIKTOK),
            ContestEvent(guild_id, 101, "Alice", channel_id, "reaction", now - timedelta(minutes=30), "react:1", CONTEST_POINTS_REACTION),
            ContestEvent(guild_id, 101, "Alice", channel_id, "reaction", now - timedelta(minutes=20), "react:2", CONTEST_POINTS_REACTION),
            ContestEvent(guild_id, 101, "Alice", channel_id, "reaction", now - timedelta(minutes=10), "react:3", CONTEST_POINTS_REACTION),

            # User 2: 5 messages (5 * 3 = 15 pts) -> 15 pts
            ContestEvent(guild_id, 102, "Bob", channel_id, "message", now - timedelta(hours=3), "msg:4", CONTEST_POINTS_MESSAGE),
            ContestEvent(guild_id, 102, "Bob", channel_id, "message", now - timedelta(hours=2), "msg:5", CONTEST_POINTS_MESSAGE),
            ContestEvent(guild_id, 102, "Bob", channel_id, "message", now - timedelta(hours=1), "msg:6", CONTEST_POINTS_MESSAGE),
            ContestEvent(guild_id, 102, "Bob", channel_id, "message", now - timedelta(minutes=50), "msg:7", CONTEST_POINTS_MESSAGE),
            ContestEvent(guild_id, 102, "Bob", channel_id, "message", now - timedelta(minutes=40), "msg:8", CONTEST_POINTS_MESSAGE),

            # User 3: 2 TikTok posts (2 * 5 = 10 pts), 1 reaction (1 pt) -> 11 pts
            ContestEvent(guild_id, 103, "Charlie", channel_id, "tiktok", now - timedelta(hours=1), "msg:9", CONTEST_POINTS_TIKTOK),
            ContestEvent(guild_id, 103, "Charlie", channel_id, "tiktok", now - timedelta(minutes=30), "msg:10", CONTEST_POINTS_TIKTOK),
            ContestEvent(guild_id, 103, "Charlie", channel_id, "reaction", now - timedelta(minutes=5), "react:4", CONTEST_POINTS_REACTION),
        ]

        inserted = await self.store.record_events(events)
        self.assertEqual(inserted, len(events))

        # Duplicate event insertion test (idempotence)
        dup_inserted = await self.store.record_events([events[0]])
        self.assertEqual(dup_inserted, 0)

        results = await self.store.aggregate(
            guild_id, now - timedelta(hours=24), now + timedelta(minutes=1)
        )

        self.assertEqual(len(results), 3)
        # Bob should be #1 with 15 pts
        self.assertEqual(results[0].user_id, 102)
        self.assertEqual(results[0].total_points, 15)
        self.assertEqual(results[0].messages, 5)

        # Alice should be #2 with 14 pts
        self.assertEqual(results[1].user_id, 101)
        self.assertEqual(results[1].total_points, 14)
        self.assertEqual(results[1].messages, 2)
        self.assertEqual(results[1].tiktoks, 1)
        self.assertEqual(results[1].reactions, 3)

        # Charlie should be #3 with 11 pts
        self.assertEqual(results[2].user_id, 103)
        self.assertEqual(results[2].total_points, 11)
        self.assertEqual(results[2].tiktoks, 2)
        self.assertEqual(results[2].reactions, 1)


class TestContestDateRanges(unittest.TestCase):
    def test_today_range(self):
        start_utc, end_utc, label = get_today_range()
        tz = _report_timezone()
        start_local = start_utc.astimezone(tz)
        self.assertEqual(start_local.hour, 0)
        self.assertEqual(start_local.minute, 0)
        self.assertEqual(start_local.second, 0)
        self.assertTrue(end_utc > start_utc)
        self.assertIn("Starting Today", label)

    def test_custom_range_valid(self):
        start_utc, end_utc = _parse_custom_contest_range("2026-09-01", "2026-09-05")
        self.assertTrue(end_utc > start_utc)

        start_time_utc, end_time_utc = _parse_custom_contest_range(
            "2026-09-01 08:00", "2026-09-01 20:00"
        )
        self.assertEqual((end_time_utc - start_time_utc).total_seconds(), 12 * 3600)

    def test_custom_range_invalid(self):
        with self.assertRaises(ValueError):
            _parse_custom_contest_range("2026-09-05", "2026-09-01")

        with self.assertRaises(ValueError):
            _parse_custom_contest_range("not-a-date", "2026-09-01")


if __name__ == "__main__":
    unittest.main()
