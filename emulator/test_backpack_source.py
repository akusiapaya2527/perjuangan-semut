from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "antwarsmobilestarling.swf-decompile/src/com/boyaa/antwars/view/screen/backpack/Backpack.as"


class BackpackSourceTests(unittest.TestCase):
    def test_tab_handlers_explicitly_select_only_the_clicked_tab(self):
        source = SOURCE.read_text()
        self.assertIn("private function setActiveTab(param1:ToggleButton)", source)
        self.assertIn("setActiveTab(btnWeapon);", source)
        self.assertIn("setActiveTab(btnEquip);", source)
        self.assertIn("setActiveTab(btnProp);", source)


if __name__ == "__main__":
    unittest.main()
