import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("emulator_backend", ROOT / "emulator.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class QuestWireTests(unittest.TestCase):
    def test_dynamic_quest_state_contains_definition_for_client(self):
        db = {"users": {"1000001": {"id": 1000001, "level": 1, "exp": 0, "currency": 0, "goods": []}}, "quests": []}
        quest = backend.create_quest(db, {
            "name": "Pakai alat",
            "description": "Gunakan alat sekali",
            "actioncode": 180,
            "times": 1,
        })
        user = backend.get_user(db, "1000001")
        rows = backend.quest_states_for_user(db, 1000001)
        self.assertEqual(rows[0][1], backend.quest_msid(quest["id"]))
        self.assertEqual(rows[0][4][0][1], backend.quest_msid(quest["id"]) * 10 + 1)
        self.assertEqual(rows[0][5]["name"], "Pakai alat")

    def test_client_source_builds_dynamic_mission_from_wire_definition(self):
        source = pathlib.Path(
            "antwarsmobilestarling.swf-decompile/src/com/boyaa/antwars/data/MissionDataList.as"
        ).read_text()
        self.assertIn("addDynamicMission", source)
        self.assertIn("_loc7_[5]", source)
        self.assertIn("missionStore.push", source)


if __name__ == "__main__":
    unittest.main()
