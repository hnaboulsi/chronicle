import json
import os
import sys
import tempfile
import unittest


class AIRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_cwd = os.getcwd()
        cls._tmpdir = tempfile.TemporaryDirectory()
        os.chdir(cls._tmpdir.name)
        os.environ["DATABASE_URL"] = "sqlite:///./test_ai_routing.db"
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)

        import database
        import models
        import agent_logic
        import llm_client

        cls.database = database
        cls.models = models
        cls.agent_logic = agent_logic
        cls.llm_client = llm_client
        cls.database.Base.metadata.drop_all(bind=cls.database.engine)
        cls.database.Base.metadata.create_all(bind=cls.database.engine)
        cls._orig_mistral_key = cls.llm_client._mistral_api_key
        cls._orig_gemini_client = cls.llm_client._gemini_client
        cls._orig_openai_key = os.environ.get("OPENAI_API_KEY")

    @classmethod
    def tearDownClass(cls):
        cls.database.Base.metadata.drop_all(bind=cls.database.engine)
        cls.database.engine.dispose()
        cls.llm_client._mistral_api_key = cls._orig_mistral_key
        cls.llm_client._gemini_client = cls._orig_gemini_client
        if cls._orig_openai_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = cls._orig_openai_key
        cls._tmpdir.cleanup()
        os.chdir(cls._old_cwd)

    def setUp(self):
        self.db = self.database.SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_sync_ai_preferences_sets_runtime_env(self):
        self.agent_logic.ensure_default_settings(self.db)
        self.agent_logic.set_state(self.db, "ai_provider", "mistral")
        self.agent_logic.set_state(self.db, "ai_fallback_providers", json.dumps(["gemini", "openai", "mistral"]))
        self.agent_logic.set_state(self.db, "ai_routing_mode", "task_aware")

        prefs = self.agent_logic.sync_ai_preferences_to_env(self.db)

        self.assertEqual(prefs["primary_provider"], "mistral")
        self.assertEqual(prefs["fallback_providers"], ["gemini", "openai"])
        self.assertEqual(os.environ["CHRONICLE_AI_PROVIDER"], "mistral")
        self.assertEqual(json.loads(os.environ["CHRONICLE_AI_FALLBACK_PROVIDERS"]), ["gemini", "openai"])
        self.assertEqual(os.environ["CHRONICLE_AI_ROUTING_MODE"], "task_aware")

    def test_task_aware_fallback_is_interactive_only(self):
        self.llm_client._mistral_api_key = "test-key"
        self.llm_client._gemini_client = object()
        os.environ["OPENAI_API_KEY"] = ""
        os.environ["CHRONICLE_AI_PROVIDER"] = "mistral"
        os.environ["CHRONICLE_AI_FALLBACK_PROVIDERS"] = json.dumps(["gemini"])
        os.environ["CHRONICLE_AI_ROUTING_MODE"] = "task_aware"

        self.assertEqual(self.llm_client._provider_order(task_type="chat"), ["mistral", "gemini"])
        self.assertEqual(self.llm_client._provider_order(task_type="hourly_summary"), ["mistral"])


if __name__ == "__main__":
    unittest.main()
