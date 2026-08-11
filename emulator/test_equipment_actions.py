import os
import sys
import unittest
import importlib.util

sys.path.insert(0, os.path.dirname(__file__))
_spec = importlib.util.spec_from_file_location("emulator_backend", os.path.join(os.path.dirname(__file__), "emulator.py"))
backend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backend)


class EquipmentActionTests(unittest.TestCase):
    def test_equip_demotes_previous_item_in_same_slot(self):
        user = {"goods": [
            {"onlyID": 1, "typeID": 11, "frameID": 1091, "position": 1, "slot": "weapon"},
            {"onlyID": 2, "typeID": 11, "frameID": 1101, "position": 0},
        ]}

        changed = backend.set_equipment_state(user, "weapon", 1, 2)

        self.assertEqual(changed["onlyID"], 2)
        self.assertEqual(user["goods"][0]["position"], 0)
        self.assertEqual(user["goods"][1]["position"], 1)
        self.assertEqual(user["goods"][1]["slot"], "weapon")

    def test_unequip_clears_slot_but_does_not_delete_item(self):
        user = {"goods": [{"onlyID": 4, "typeID": 6, "frameID": 1111, "position": 1, "slot": "hat"}]}

        changed = backend.set_equipment_state(user, "hat", 0, 4)

        self.assertEqual(changed["position"], 0)
        self.assertEqual(changed["onlyID"], 4)


if __name__ == "__main__":
    unittest.main()
