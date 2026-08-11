import os
import sys
import unittest
import importlib.util

sys.path.insert(0, os.path.dirname(__file__))
_spec = importlib.util.spec_from_file_location("emulator_backend", os.path.join(os.path.dirname(__file__), "emulator.py"))
backend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backend)


class QuestBackendTests(unittest.TestCase):
    def setUp(self):
        self.db = {
            "users": {"7": {"id": 7, "level": 3, "exp": 20, "currency": 0, "goods": []}},
            "quests": [], "ledger": [],
        }

    def test_quest_state_tracks_level_and_exposes_dynamic_definition(self):
        quest = backend.create_quest(self.db, {
            "name": "Naik level", "description": "Capai level tiga", "mtype": 1,
            "actioncode": 117, "times": 3, "level": 1, "reward_coin": 10,
        })

        states = backend.quest_states_for_user(self.db, 7)

        self.assertEqual(len(states), 1)
        self.assertEqual(states[0][2], 1)
        self.assertEqual(states[0][4][0][2], 3)
        self.assertEqual(states[0][5]["name"], "Naik level")
        self.assertGreater(states[0][1], 300000)

    def test_action_progress_and_reward_are_single_use(self):
        quest = backend.create_quest(self.db, {
            "name": "Pakai alat", "description": "Pakai alat", "actioncode": 180,
            "times": 2, "reward_coin": 50, "reward_exp": 5,
        })
        backend.advance_quests(self.db, 7, 180, amount=2)

        result = backend.claim_quest_reward(self.db, 7, quest["id"])
        again = backend.claim_quest_reward(self.db, 7, quest["id"])

        self.assertEqual(result[1]["currency"], 50)
        self.assertEqual(result[0]["mpoint"], 25)
        self.assertEqual(again["error"], "quest already rewarded")

    def test_quest_crud_updates_persistent_collection_shape(self):
        quest = backend.create_quest(self.db, {"name": "Awal", "actioncode": 176, "times": 1})
        backend.update_quest(self.db, quest["id"], {"name": "Updated", "enabled": False})
        self.assertEqual(self.db["quests"][0]["name"], "Updated")
        self.assertFalse(self.db["quests"][0]["enabled"])
        self.assertTrue(backend.delete_quest(self.db, quest["id"]))
        self.assertEqual(self.db["quests"], [])

    def test_walkthrough_quests_match_game_actions(self):
        quests = backend.walkthrough_quests()
        actions = {int(q["actioncode"]) for q in quests}
        self.assertTrue({117, 115, 180, 176, 170}.issubset(actions))
        self.assertTrue(all(q["enabled"] for q in quests))


if __name__ == "__main__":
    unittest.main()
