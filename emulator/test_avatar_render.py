import os
import sys
import unittest
import importlib.util

sys.path.insert(0, os.path.dirname(__file__))
_spec = importlib.util.spec_from_file_location("emulator_backend", os.path.join(os.path.dirname(__file__), "emulator.py"))
backend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backend)


class AvatarRenderTests(unittest.TestCase):
    def test_avatar_gear_uses_normalized_equipment_only(self):
        user = {
            "sex": 0,
            "goods": [
                {"onlyID": 1, "typeID": 11, "frameID": 1091, "position": 1, "slot": "weapon"},
                {"onlyID": 2, "typeID": 11, "frameID": 1101, "position": 1, "slot": "weapon"},
                {"onlyID": 3, "typeID": 8, "frameID": 1201, "position": 1, "slot": "wing"},
                {"onlyID": 4, "typeID": 26, "frameID": 1001, "position": 1},
            ],
        }

        gear = backend.avatar_gear_for_user(user)

        self.assertEqual([(g["typeID"], g["frameID"]) for g in gear], [(11, 1101), (8, 1201)])


if __name__ == "__main__":
    unittest.main()
