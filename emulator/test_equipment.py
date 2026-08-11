import os
import sys
import unittest
import importlib.util

sys.path.insert(0, os.path.dirname(__file__))
_spec = importlib.util.spec_from_file_location("emulator_backend", os.path.join(os.path.dirname(__file__), "emulator.py"))
emulator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emulator)


class EquipmentNormalizationTests(unittest.TestCase):
    def test_equipped_goods_use_one_record_per_slot_and_keep_bag_items(self):
        user = {
            "goods": [
                {"onlyID": 1, "typeID": 11, "frameID": 1091, "position": 1, "slot": "weapon"},
                {"onlyID": 2, "typeID": 11, "frameID": 1101, "position": 1, "slot": "weapon"},
                {"onlyID": 3, "typeID": 1, "frameID": 1011, "position": 0},
            ]
        }

        normalized = emulator.normalize_user_goods(user)

        self.assertEqual([g["onlyID"] for g in normalized], [1, 2, 3])
        self.assertEqual(normalized[0]["position"], 0)
        self.assertEqual([g["onlyID"] for g in emulator.equipped_goods(user)], [2])

    def test_slot_is_derived_for_supported_equipment(self):
        self.assertEqual(emulator.equipment_slot_for_good({"typeID": 6}), "hat")
        self.assertEqual(emulator.equipment_slot_for_good({"typeID": 11}), "weapon")
        self.assertEqual(emulator.equipment_slot_for_good({"typeID": 25}), "")


if __name__ == "__main__":
    unittest.main()
