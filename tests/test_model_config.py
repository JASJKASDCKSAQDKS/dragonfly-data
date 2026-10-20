import unittest

from jarvis import config


class ModelConfigTests(unittest.TestCase):
    def test_default_model_matches_configured_provider(self):
        # The active model must always be a non-empty string consistent
        # with the configured provider — not a hardcoded name, so tests
        # survive model swaps in .env.
        model = config.get_model_name()
        self.assertTrue(model, "Active model name must be non-empty")
        if config.MODEL_PROVIDER == "ollama":
            self.assertEqual(model, config.OLLAMA_MODEL)
        elif config.MODEL_PROVIDER == "gemini":
            self.assertIn("gemini", model.lower())

    def test_set_model_name_updates_config(self):
        orig = config.get_model_name()
        res = config.set_model_name("test-model-123", persist=False)
        self.assertEqual(res, "test-model-123")
        self.assertEqual(config.get_model_name(), "test-model-123")
        config.set_model_name(orig, persist=False)
        self.assertEqual(config.get_model_name(), orig)

    def test_response_settings_are_stable_for_coding(self):
        self.assertLessEqual(config.TEMPERATURE, 0.6)
        self.assertGreater(config.MAX_TOKENS, 1000)



if __name__ == "__main__":
    unittest.main()
