from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

try:
    import pcbnew

    HAS_PCBNEW = True
except ImportError:
    HAS_PCBNEW = False

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAYOUT_SCRIPT_DIR = ROOT / "packs/hardware/kicad-pcbnew-layout/scripts"
if HAS_PCBNEW and str(LAYOUT_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(LAYOUT_SCRIPT_DIR))


@unittest.skipUnless(HAS_PCBNEW, "requires KiCad pcbnew")
class PcbnewLayoutTemplateKicadTests(unittest.TestCase):
    def setUp(self) -> None:
        import pcbnew_layout_template as plt_mod

        self.plt = plt_mod

    def test_parse_schematic_unit1_uuids(self) -> None:
        sch = """(kicad_sch
\t(symbol (lib_id "Device:R") (unit 1) (uuid "11111111-1111-1111-1111-111111111111")
\t\t(property "Reference" "R1")
\t)
\t(symbol (lib_id "Amplifier_Operational:TL072") (unit 2) (uuid "22222222-2222-2222-2222-222222222222")
\t\t(property "Reference" "U1")
\t)
\t(symbol (lib_id "Amplifier_Operational:TL072") (unit 1) (uuid "33333333-3333-3333-3333-333333333333")
\t\t(property "Reference" "U1")
\t)
\t(symbol (lib_id "power:GND") (unit 1) (uuid "44444444-4444-4444-4444-444444444444")
\t\t(property "Reference" "#PWR01")
\t)
)"""
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "test.kicad_sch"
            p.write_text(sch, encoding="utf-8")
            uuids = self.plt.parse_schematic_unit1_uuids(p)
            self.assertEqual(
                uuids,
                {
                    "R1": "11111111-1111-1111-1111-111111111111",
                    "U1": "33333333-3333-3333-3333-333333333333",
                },
            )

    def test_load_footprint_accepts_str_and_path_custom_dirs(self) -> None:
        fp_mod = """(footprint "CustomPart"
\t(layer "F.Cu")
\t(fp_text reference "REF**" (at 0 0) (layer "F.SilkS"))
\t(fp_text value "CustomPart" (at 0 1) (layer "F.Fab"))
)"""
        with tempfile.TemporaryDirectory() as td:
            pretty = pathlib.Path(td) / "MyLib.pretty"
            pretty.mkdir()
            (pretty / "CustomPart.kicad_mod").write_text(fp_mod, encoding="utf-8")

            fp_str = self.plt.load_footprint("MyLib", "CustomPart", custom_fp_dirs=[td])
            fp_path = self.plt.load_footprint(
                "MyLib", "CustomPart", custom_fp_dirs=[pathlib.Path(td)]
            )
            self.assertEqual(fp_str.GetValue(), "CustomPart")
            self.assertEqual(fp_path.GetValue(), "CustomPart")

    def test_create_base_board_origin_and_fiducials(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            b1_path = pathlib.Path(td) / "b1.kicad_pcb"
            b1 = self.plt.create_base_board(b1_path, 100.0, 40.0, 130.0, 148.0)
            ds1 = b1.GetDesignSettings()
            self.assertEqual(pcbnew.ToMM(ds1.GetAuxOrigin().x), 100.0)
            self.assertEqual(pcbnew.ToMM(ds1.GetAuxOrigin().y), 40.0)
            self.assertEqual(pcbnew.ToMM(ds1.GetGridOrigin().x), 100.0)

            b2_path = pathlib.Path(td) / "b2.kicad_pcb"
            b2 = self.plt.create_base_board(
                b2_path, 100.0, 40.0, 130.0, 148.0, set_board_origin=False
            )
            ds2 = b2.GetDesignSettings()
            self.assertEqual(ds2.GetAuxOrigin().x, 0)
            self.assertEqual(ds2.GetAuxOrigin().y, 0)

            stock_fid = (
                self.plt.FP_DIR / "Fiducial.pretty/Fiducial_1mm_Mask2mm.kicad_mod"
            )
            if stock_fid.exists():
                fids = self.plt.add_fiducials(
                    b1, {"FID1": (105.0, 45.0)}, is_back=False
                )
                self.assertEqual(len(fids), 1)
                fid = fids["FID1"]
                self.assertTrue(fid.IsDNP())
                self.assertTrue(fid.IsExcludedFromBOM())
                self.assertTrue(fid.IsExcludedFromPosFiles())
                if hasattr(fid, "IsBoardOnly"):
                    self.assertTrue(fid.IsBoardOnly())
