import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(__file__))

import agent_logic
import main
from models import ActivityLog, Base


class AnalyticsTodayTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        agent_logic.ensure_default_settings(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_active_minutes_excludes_idle_samples(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.db.add_all(
            [
                ActivityLog(device="mac", app_name="Cursor", window_title="work", is_idle=False, timestamp=now),
                ActivityLog(device="mac", app_name="Cursor", window_title="break", is_idle=True, timestamp=now),
            ]
        )
        self.db.commit()
        agent_logic.set_state(self.db, "polling_interval_seconds", "60")

        payload = asyncio.run(main.analytics_today(self.db))

        self.assertEqual(payload["total_active_minutes"], 1)
        self.assertEqual(payload["productive_minutes"], 1)
        self.assertEqual(payload["productive_pct"], 100)
        self.assertEqual(payload["idle_log_count"], 1)


if __name__ == "__main__":
    unittest.main()
