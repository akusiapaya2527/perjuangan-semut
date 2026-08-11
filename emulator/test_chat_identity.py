import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("emulator_backend", ROOT / "emulator.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class FakeGame:
    def __init__(self):
        self.clients = {"sender", "target", "other"}
        self.client_uids = {"sender": 8, "target": 9, "other": 1}
        self.sent = []

    def send_cmd(self, conn, cmd, writer):
        self.sent.append((conn, cmd, writer.frame(1002)))


class ChatIdentityTests(unittest.TestCase):
    def test_private_chat_uses_connection_uid_and_only_target(self):
        old_db, old_server, old_save = backend.DB, backend.GAME_SRV, backend.save_db
        try:
            backend.DB = {"users": {"8": {"id": 8, "name": "Aryma"},
                                    "9": {"id": 9, "name": "Bima"}}, "chat": []}
            backend.save_db = lambda db: None
            fake = FakeGame()
            backend.GAME_SRV = fake
            backend.push_private(8, 0, "halo", to_uid=9, conn="sender")
            self.assertEqual([(row[0], row[1]) for row in fake.sent], [("target", 1002)])
            self.assertEqual(backend.DB["chat"][0]["name"], "Aryma")
            self.assertEqual(backend.DB["chat"][0]["uid"], 8)
        finally:
            backend.DB, backend.GAME_SRV, backend.save_db = old_db, old_server, old_save


if __name__ == "__main__":
    unittest.main()
