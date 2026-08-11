import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("emulator_backend", ROOT / "emulator.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class FriendshipTests(unittest.TestCase):
    def setUp(self):
        self.db = {"users": {
            "1": {"id": 1, "name": "Satu", "level": 2, "sex": 1, "goods": []},
            "2": {"id": 2, "name": "Dua", "level": 3, "sex": 0, "goods": []},
            "3": {"id": 3, "name": "Tiga", "level": 4, "sex": 1, "goods": []},
        }, "friendships": [], "friend_requests": []}

    def test_search_isolated_and_request_accept_delete(self):
        self.assertEqual([u["id"] for u in backend.search_users(self.db, 1, "a")], [2, 3])
        request = backend.request_friend(self.db, 1, 2)
        self.assertEqual(request["status"], "pending")
        self.assertEqual(backend.friend_list_for_user(self.db, 2), [])
        self.assertTrue(backend.accept_friend(self.db, 2, 1))
        self.assertEqual([f["id"] for f in backend.friend_list_for_user(self.db, 1)], [2])
        self.assertEqual([f["id"] for f in backend.friend_list_for_user(self.db, 2)], [1])
        self.assertTrue(backend.delete_friend(self.db, 1, 2))
        self.assertEqual(backend.friend_list_for_user(self.db, 1), [])

    def test_pending_requests_are_owner_specific(self):
        backend.request_friend(self.db, 1, 2)
        backend.request_friend(self.db, 3, 2)
        self.assertEqual([r["from_id"] for r in backend.pending_friend_requests(self.db, 2)], [1, 3])
        self.assertEqual(backend.pending_friend_requests(self.db, 1), [])


if __name__ == "__main__":
    unittest.main()
