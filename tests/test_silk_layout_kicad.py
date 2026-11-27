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
SILK_SCRIPT_DIR = ROOT / "packs/hardware/kicad-silkscreen-markup/scripts"
if HAS_PCBNEW and str(SILK_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SILK_SCRIPT_DIR))


BASE_BOARD_PCB = """(kicad_pcb
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(general (thickness 1.6))
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(25 "Edge.Cuts" user)
\t\t(33 "B.Fab" user)
\t\t(35 "F.Fab" user)
\t)
\t(setup
\t\t(pad_to_mask_clearance 0)
\t\t(grid_origin 100 40)
\t\t(aux_axis_origin 100 40)
\t)
\t(net 0 "")
\t(gr_rect
\t\t(start 100 40)
\t\t(end 140 80)
\t\t(stroke (width 0.05) (type solid))
\t\t(fill no)
\t\t(layer "Edge.Cuts")
\t)
\t(gr_text "CUSTOM FAB NOTE"
\t\t(at 120 84 0)
\t\t(layer "B.Fab")
\t\t(effects (font (size 0.8 0.8) (thickness 0.15)) (justify mirror))
\t)
)"""


@unittest.skipUnless(HAS_PCBNEW, "requires KiCad pcbnew")
class SilkLayoutKicadTests(unittest.TestCase):
    def setUp(self) -> None:
        import silk_annotator as sa
        import silk_layout as sl

        self.sa = sa
        self.sl = sl

    def _add_test_resistor(
        self, board: pcbnew.BOARD, ref: str, x: float, y: float
    ) -> None:
        fp = pcbnew.FOOTPRINT(board)
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        fp.SetReference(ref)
        fp.SetValue("10k")
        for idx, dx in enumerate((-0.8, 0.8), start=1):
            pad = pcbnew.PAD(fp)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetShape(pcbnew.PAD_SHAPE_RECT)
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.7), pcbnew.FromMM(0.8)))
            pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x + dx), pcbnew.FromMM(y)))
            lset = pcbnew.LSET()
            lset.AddLayer(pcbnew.F_Cu)
            lset.AddLayer(pcbnew.F_Mask)
            pad.SetLayerSet(lset)
            pad.SetName(str(idx))
            fp.Add(pad)

    def test_extract_apply_preserves_unfilled_dot_arc_and_custom_bfab(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pcb_path = pathlib.Path(td) / "board.kicad_pcb"
            layout_path = pathlib.Path(td) / "silk_layout.json"
            pcb_path.write_text(BASE_BOARD_PCB, encoding="utf-8")

            board = pcbnew.LoadBoard(str(pcb_path))
            self._add_test_resistor(board, "R1", 120.0, 60.0)
            # Unfilled circle dot on F.SilkS
            self.sa.add_silk_dot(
                board, pcbnew.F_SilkS, 108.0, 50.0, radius=0.4, filled=False
            )
            # Unfilled group rect surrounding R1 (110..130 x 50..70)
            self.sa.add_silk_rect(
                board, pcbnew.F_SilkS, 110.0, 50.0, 130.0, 70.0, filled=False
            )
            # Unsupported board silk arc (should be preserved across --apply)
            arc = pcbnew.PCB_SHAPE(board)
            arc.SetShape(pcbnew.SHAPE_T_ARC)
            arc.SetLayer(pcbnew.F_SilkS)
            arc.SetArcGeometry(
                pcbnew.VECTOR2I(pcbnew.FromMM(105.0), pcbnew.FromMM(45.0)),
                pcbnew.VECTOR2I(pcbnew.FromMM(106.0), pcbnew.FromMM(44.0)),
                pcbnew.VECTOR2I(pcbnew.FromMM(107.0), pcbnew.FromMM(45.0)),
            )
            arc.SetWidth(pcbnew.FromMM(0.15))
            board.Add(arc)
            board.Save(str(pcb_path))

            rc_ext = self.sl.main(
                ["--pcb", str(pcb_path), "--extract", "--layout", str(layout_path)]
            )
            self.assertEqual(rc_ext, 0)
            layout = self.sl.load_silk_layout(layout_path)
            self.assertEqual(len(layout["dots"]), 1)
            self.assertFalse(layout["dots"][0]["filled"])
            layout["footprints"]["R1"] = "auto"
            layout_path.write_text(
                self.sl.format_silk_layout_json(layout), encoding="utf-8"
            )

            rc_app = self.sl.main(
                ["--pcb", str(pcb_path), "--apply", "--layout", str(layout_path)]
            )
            self.assertEqual(rc_app, 0)

            reloaded = pcbnew.LoadBoard(str(pcb_path))
            dots = [
                d
                for d in reloaded.GetDrawings()
                if isinstance(d, pcbnew.PCB_SHAPE)
                and d.GetLayer() == pcbnew.F_SilkS
                and d.GetShape() == pcbnew.SHAPE_T_CIRCLE
            ]
            arcs = [
                d
                for d in reloaded.GetDrawings()
                if isinstance(d, pcbnew.PCB_SHAPE)
                and d.GetLayer() == pcbnew.F_SilkS
                and d.GetShape() == pcbnew.SHAPE_T_ARC
            ]
            bfab_texts = [
                d.GetText()
                for d in reloaded.GetDrawings()
                if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() == pcbnew.B_Fab
            ]
            self.assertEqual(len(dots), 1)
            self.assertFalse(dots[0].IsSolidFill())
            self.assertEqual(len(arcs), 1)
            self.assertEqual(bfab_texts, ["CUSTOM FAB NOTE"])

            # --restamp-fab-notes should replace custom B.Fab with standard notes
            rc_fab = self.sl.main(
                [
                    "--pcb",
                    str(pcb_path),
                    "--apply",
                    "--restamp-fab-notes",
                    "--layout",
                    str(layout_path),
                ]
            )
            self.assertEqual(rc_fab, 0)
            reloaded2 = pcbnew.LoadBoard(str(pcb_path))
            bfab_texts2 = [
                d.GetText()
                for d in reloaded2.GetDrawings()
                if isinstance(d, pcbnew.PCB_TEXT) and d.GetLayer() == pcbnew.B_Fab
            ]
            self.assertIn("FAB NOTES: 2L FR4 | THICKNESS: 1.6mm | 1oz CU", bfab_texts2)
            self.assertNotIn("CUSTOM FAB NOTE", bfab_texts2)

    def test_apply_returns_nonzero_when_inspection_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pcb_path = pathlib.Path(td) / "overlap.kicad_pcb"
            layout_path = pathlib.Path(td) / "silk_layout.json"
            pcb_path.write_text(BASE_BOARD_PCB, encoding="utf-8")

            board = pcbnew.LoadBoard(str(pcb_path))
            self._add_test_resistor(board, "R1", 120.0, 60.0)
            board.Save(str(pcb_path))

            # Intentionally place R1 text directly on top of R1 pads (keepout hit -> FAIL).
            bad_layout = {
                "version": 1,
                "board_origin_mm": [100.0, 40.0],
                "board_size_mm": [40.0, 40.0],
                "qr_rects": [],
                "dots": [],
                "segments": [],
                "board_texts": [],
                "footprints": {
                    "R1": {
                        "ref": {
                            "layer": "F.SilkS",
                            "x": 20.0,
                            "y": 20.0,
                            "deg": 0.0,
                            "height": 0.8,
                            "thickness": 0.15,
                        },
                        "texts": [],
                    }
                },
            }
            layout_path.write_text(
                self.sl.format_silk_layout_json(bad_layout), encoding="utf-8"
            )
            rc = self.sl.main(
                ["--pcb", str(pcb_path), "--apply", "--layout", str(layout_path)]
            )
            self.assertEqual(rc, 1)
