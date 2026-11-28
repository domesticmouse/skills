from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PANEL_SCRIPT_DIR = ROOT / "packs/hardware/eurorack-panel/scripts"
if str(PANEL_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(PANEL_SCRIPT_DIR))

import generate_eurorack_panel as gep

SAMPLE_PCB = """(kicad_pcb
\t(version 20260206)
\t(gr_rect (start 100 20) (end 130 128) (stroke (width 0.05) (type solid)) (fill no) (layer "Edge.Cuts"))
\t(footprint "Potentiometer_THT:Potentiometer_Alps_RK09K_Single_Vertical"
\t\t(layer "F.Cu")
\t\t(at 105.5 53.5 90)
\t\t(property "Reference" "RV1")
\t\t(property "Value" "TUNE")
\t)
\t(footprint "Button_Switch_THT:SW_PUSH-12mm"
\t\t(layer "F.Cu")
\t\t(at 108.05 90.0)
\t\t(property "Reference" "SW2")
\t\t(property "Value" "TRIG")
\t)
\t(footprint "Button_Switch_THT:SW_PUSH-12mm"
\t\t(layer "F.Cu")
\t\t(at 108.05 110.0)
\t\t(property "Reference" "SW3")
\t\t(property "Value" "MODE")
\t\t(fp_circle (center 6.25 2.5) (end 9.8 2.5) (layer "F.SilkS"))
\t)
)
"""


class GenerateEurorackPanelTests(unittest.TestCase):
    def test_extract_pot_default_offset_and_pushbutton_12mm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pcb_path = pathlib.Path(td) / "main.kicad_pcb"
            pcb_path.write_text(SAMPLE_PCB, encoding="utf-8")
            bbox, controls, _ = gep.parse_main_pcb(pcb_path)
            self.assertEqual(bbox["min_x"], 100.0)
            by_ref = {c["ref"]: c for c in controls}

            rv1 = by_ref["RV1"]
            self.assertEqual(rv1["kind"], "pot")
            self.assertAlmostEqual(rv1["bushing_x"], 108.0, places=3)
            self.assertAlmostEqual(rv1["bushing_y"], 46.0, places=3)

            for ref, expected_y in (("SW2", 92.5), ("SW3", 112.5)):
                sw = by_ref[ref]
                self.assertEqual(sw["kind"], "pushbutton_12mm")
                self.assertEqual(sw["drill_mm"], 12.5)
                self.assertFalse(sw["grounded"])
                self.assertAlmostEqual(sw["bushing_x"], 114.3, places=3)
                self.assertAlmostEqual(sw["bushing_y"], expected_y, places=3)

            fp_sexpr = gep.format_jack_footprint("ns", by_ref["SW2"], 100.0, 9.75)
            self.assertIn("Eurorack_Panel:PushButtonHole_12mm_12.5mm_NPTH", fp_sexpr)
            self.assertIn("np_thru_hole", fp_sexpr)
