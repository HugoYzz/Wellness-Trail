import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base
from app.services.provider_settings import (
    get_active_provider,
    get_provider_preferences,
    set_provider_preference,
)


class ProviderPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_defaults_to_local_ollama(self):
        provider_id, models = get_provider_preferences(self.db)
        self.assertEqual(provider_id, "ollama")
        self.assertEqual(models, {})

    def test_selected_provider_and_model_are_persisted(self):
        set_provider_preference(self.db, "deepseek", "deepseek-chat")
        provider_id, models = get_provider_preferences(self.db)
        self.assertEqual(provider_id, "deepseek")
        self.assertEqual(models["deepseek"], "deepseek-chat")
        self.assertEqual(get_active_provider(self.db).provider_id, "deepseek")


if __name__ == "__main__":
    unittest.main()
