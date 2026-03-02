import unittest
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import agent_logic
from models import Base, ActivityLog
from main import _coerce_bool, _parse_event_time, _fallback_summary_payload


class ZoneAndSummaryHelperTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_slugify_normalizes_and_trims(self):
        self.assertEqual(agent_logic.normalize_zone_slug("  UC Berkeley / Doe Library  "), "uc-berkeley-doe-library")
        self.assertEqual(agent_logic.normalize_zone_slug("A__B__C"), "a-b-c")

    def test_slug_regex_accepts_and_rejects_expected_values(self):
        self.assertTrue(agent_logic.SLUG_RE.match("home"))
        self.assertTrue(agent_logic.SLUG_RE.match("zone-1"))
        self.assertIsNone(agent_logic.SLUG_RE.match("BadSlug"))
        self.assertIsNone(agent_logic.SLUG_RE.match("bad_slug"))

    def test_bool_coercion(self):
        self.assertTrue(_coerce_bool("true"))
        self.assertTrue(_coerce_bool("1"))
        self.assertFalse(_coerce_bool("false", True))
        self.assertFalse(_coerce_bool("0", True))
        self.assertTrue(_coerce_bool(None, True))

    def test_parse_event_time(self):
        self.assertIsNotNone(_parse_event_time("2026-03-02T10:00:00Z"))
        self.assertIsNotNone(_parse_event_time("2026-03-02T10:00:00+00:00"))
        naive = _parse_event_time("2026-03-02T10:00:00")
        self.assertIsNotNone(naive)
        self.assertEqual(naive.tzinfo, timezone.utc)
        self.assertIsNone(_parse_event_time("not-a-date"))

    def test_zone_upsert_parses_false_string(self):
        zone = agent_logic.upsert_zone(
            self.db,
            {
                "name": "Home",
                "slug": "home",
                "radius_meters": 80,
                "enabled": "false",
                "zone_type": "home",
            },
        )
        self.assertFalse(zone["enabled"])

    def test_user_day_bounds_follow_user_timezone(self):
        agent_logic.set_state(self.db, "user_timezone", "America/New_York")
        now = datetime(2026, 3, 1, 6, 30, tzinfo=timezone.utc)
        start, end = agent_logic.user_day_bounds_utc(self.db, now)
        self.assertEqual(agent_logic.local_day_key(self.db, now), "2026-03-01")
        self.assertEqual(start, datetime(2026, 3, 1, 5, 0))
        self.assertEqual(end, datetime(2026, 3, 2, 5, 0))

    def test_ios_fallback_summary_never_uses_none_placeholders(self):
        entry = ActivityLog(
            device="ios",
            activity_type=None,
            location_label=None,
            battery_pct=None,
            steps_today=None,
        )
        payload = _fallback_summary_payload(entry, [])
        self.assertTrue(payload["summary_text"])
        self.assertNotIn("None", payload["summary_text"])
        self.assertTrue(payload["fallback_used"])
        self.assertIn("summary", payload)


if __name__ == "__main__":
    unittest.main()
