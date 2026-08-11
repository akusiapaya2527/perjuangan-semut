import importlib.util
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("emulator_backend", ROOT / "emulator.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.db = {"users": {}, "auth_users": {}, "auth_sessions": {}}

    def test_register_login_session_and_logout(self):
        registered = backend.auth_register(self.db, "Player@Example.com", "secret12", "Player", "male")
        self.assertTrue(registered["ok"])
        game_uid = registered["user"]["game_uid"]
        self.assertIn(str(game_uid), self.db["users"])
        self.assertEqual(self.db["users"][str(game_uid)]["name"], "Player")
        self.assertEqual(self.db["users"][str(game_uid)]["sex"], 0)
        self.assertTrue(self.db["users"][str(game_uid)]["goods"])

        logged = backend.auth_login(self.db, "player@example.com", "secret12")
        self.assertTrue(logged["ok"])
        self.assertTrue(logged["token"])
        self.assertEqual(logged["user"]["game_uid"], game_uid)
        self.assertEqual(backend.auth_me(self.db, logged["token"])["email"], "player@example.com")

        self.assertTrue(backend.auth_logout(self.db, logged["token"]))
        self.assertIsNone(backend.auth_me(self.db, logged["token"]))

    def test_duplicate_or_invalid_credentials_are_rejected(self):
        backend.auth_register(self.db, "player@example.com", "secret12", "Player")
        self.assertFalse(backend.auth_register(self.db, "PLAYER@example.com", "secret12", "Other")["ok"])
        self.assertFalse(backend.auth_login(self.db, "player@example.com", "wrongpass")["ok"])

    def test_gender_is_required_to_be_a_supported_value(self):
        result = backend.auth_register(self.db, "player@example.com", "secret12", "Player", "robot")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
