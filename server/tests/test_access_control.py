import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.database import get_db
from app.models import Base
from app.services import access_control


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.original_session_factory = main_module.SessionLocal
        main_module.SessionLocal = self.session_factory

        def override_db():
            with self.session_factory() as db:
                yield db

        main_module.app.dependency_overrides[get_db] = override_db

    def tearDown(self):
        main_module.app.dependency_overrides.clear()
        main_module.SessionLocal = self.original_session_factory
        self.engine.dispose()

    def test_pin_hash_is_salted_and_verifiable(self):
        encoded = access_control.hash_pin("135790", salt=bytes(range(16)))
        self.assertNotIn("135790", encoded)
        self.assertTrue(access_control.verify_pin("135790", encoded))
        self.assertFalse(access_control.verify_pin("135791", encoded))

    def test_business_api_requires_setup_then_session(self):
        with TestClient(main_module.app) as client:
            blocked = client.get("/api/records")
            self.assertEqual(blocked.status_code, 428)
            self.assertEqual(client.get("/api/chats").status_code, 428)
            self.assertEqual(client.delete("/api/records/1").status_code, 428)

            setup = client.post("/api/auth/setup", json={"pin": "135790"})
            self.assertEqual(setup.status_code, 200)
            self.assertIn(access_control.COOKIE_NAME, client.cookies)
            self.assertEqual(client.get("/api/records").status_code, 200)

            client.post("/api/auth/logout")
            self.assertEqual(client.get("/api/records").status_code, 401)
            self.assertEqual(
                client.post("/api/auth/login", json={"pin": "000000"}).status_code,
                401,
            )
            self.assertEqual(
                client.post("/api/auth/login", json={"pin": "135790"}).status_code,
                200,
            )
            self.assertEqual(client.get("/api/settings/export").status_code, 200)

    def test_pin_validation_rejects_short_or_non_numeric_values(self):
        for invalid in ("12345", "abcdef", "1234567890123"):
            with self.assertRaises(ValueError):
                access_control.hash_pin(invalid)


if __name__ == "__main__":
    unittest.main()
