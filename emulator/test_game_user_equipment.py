import importlib.util
import os
import sys
import unittest


HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
spec = importlib.util.spec_from_file_location("emulator_backend", os.path.join(HERE, "emulator.py"))
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class GameUserEquipmentTests(unittest.TestCase):
    def test_game_socket_uses_logged_in_user_goods(self):
        backend.DB["users"]["1000002"] = {
            "id": 1000002, "name": "aryma", "sex": 1, "level": 1,
            "currency": 10000, "exp": 0, "wins": 0, "losses": 0,
            "goods": [{"onlyID": 1, "typeID": 11, "frameID": 1091,
                       "count": 1, "position": 1, "amount": 1,
                       "attribute": "", "synthesis": "", "expiration": 0,
                       "strengthen": 0, "term": 0, "isbind": 0, "color": 0}],
        }
        server = backend.GameServer(0, "TEST")
        conn = object()
        frames = [(1001, backend.P.Writer().body), (3014, backend.P.Writer().body)]
        login = backend.P.Writer()
        login.int(1000002)
        login.string("session-key")
        frames[0] = (1001, bytes(login.body))
        request = backend.P.Writer()
        request.int(1000002)
        frames[1] = (3014, bytes(request.body))
        sent = []
        server.recv_frame = lambda _conn: frames.pop(0) if frames else None
        server.send_cmd = lambda _conn, cmd, writer: sent.append((cmd, bytes(writer.body)))

        server.session(conn, ("test", 0))

        cmd, body = next(item for item in sent if item[0] == 3014)
        reader = backend.P.Reader(body)
        self.assertEqual(1000002, reader.int())
        self.assertEqual(2, reader.short())
        self.assertEqual(1, reader.int())
        self.assertEqual(1, reader.int())  # onlyID of aryma's equipped weapon

    def test_flashapi_uses_request_mid_for_weapon_queue(self):
        backend.UID = 1000001
        result = backend.handle_flashapi({"mid": 1000002,
                                          "method": "GameProps.get_fight_weapons",
                                          "param": []})
        self.assertEqual(0, result["ret"])
        self.assertEqual(1, result["weapon"][0][0])


if __name__ == "__main__":
    unittest.main()
