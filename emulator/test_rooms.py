import importlib.util
import os
import sys
import unittest


HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("emulator_backend", os.path.join(HERE, "emulator.py"))
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class RoomVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.server = backend.BattleServer(0, "TEST")
        self.server.client_uids = {}
        self.server.rooms = {}
        self.server.room_seq = 0
        self.sent = []
        self.server.send_cmd = lambda conn, cmd, writer: self.sent.append(
            (conn, cmd, bytes(writer.body))
        )
        self.one = object()
        self.two = object()
        self.server.client_uids[self.one] = 1000001
        self.server.client_uids[self.two] = 1000002

    def test_room_is_listed_and_joinable_by_another_user(self):
        room_id = self.server.create_room(self.one, "", 1, 0)
        self.sent.clear()

        rows = self.server.room_list_rows()
        self.assertEqual([room_id], [row[0] for row in rows])
        self.assertEqual(1, rows[0][5])
        self.assertEqual(4, rows[0][6])

        self.server.join_room(self.two, room_id, "")
        self.assertEqual(2, len(self.server.rooms[room_id]["players"]))
        self.assertIn((self.two, 5), [(conn, cmd) for conn, cmd, _ in self.sent])
        self.assertIn((self.one, 6), [(conn, cmd) for conn, cmd, _ in self.sent])


if __name__ == "__main__":
    unittest.main()
