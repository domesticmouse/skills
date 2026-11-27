from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "packs/hardware/kicad-silkscreen-markup/scripts"

if HAS_PIL and str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


@unittest.skipUnless(HAS_PIL, "requires Pillow")
class RenderSilkPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        import render_silk_preview as rsp

        self.rsp = rsp

    def test_parse_sexpr_edge_bounds_ignores_earlier_silks_rect(self) -> None:
        pcb_text = """(kicad_pcb
\t(version 20260206)
\t(gr_rect
\t\t(start 123.8 41.0)
\t\t(end 128.8 46.0)
\t\t(stroke (width 0.15) (type solid))
\t\t(fill yes)
\t\t(layer "F.SilkS")
\t)
\t(gr_line
\t\t(start 101.0 41.0)
\t\t(end 110.0 41.0)
\t\t(stroke (width 0.2) (type solid))
\t\t(layer "B.SilkS")
\t)
\t(gr_rect
\t\t(start 100.0 40.0)
\t\t(end 130.0 148.0)
\t\t(stroke (width 0.05) (type solid))
\t\t(fill no)
\t\t(layer "Edge.Cuts")
\t)
)"""
        with tempfile.TemporaryDirectory() as td:
            pcb_path = pathlib.Path(td) / "board.kicad_pcb"
            pcb_path.write_text(pcb_text, encoding="utf-8")
            self.assertEqual(self.rsp._parse_sexpr_edge_bounds(pcb_path), (30.0, 108.0))

    def test_parse_sexpr_edge_bounds_supports_lines_and_poly(self) -> None:
        pcb_lines = """(kicad_pcb
\t(gr_line (start 10 20) (end 50 20) (layer "Edge.Cuts"))
\t(gr_line (start 50 20) (end 50 80) (layer "Edge.Cuts"))
\t(gr_line (start 50 80) (end 10 80) (layer "Edge.Cuts"))
\t(gr_line (start 10 80) (end 10 20) (layer "Edge.Cuts"))
)"""
        pcb_poly = """(kicad_pcb
\t(gr_poly
\t\t(pts (xy 0 0) (xy 25.5 0) (xy 25.5 100.25) (xy 0 100.25))
\t\t(layer "Edge.Cuts")
\t)
)"""
        with tempfile.TemporaryDirectory() as td:
            p1 = pathlib.Path(td) / "lines.kicad_pcb"
            p1.write_text(pcb_lines, encoding="utf-8")
            self.assertEqual(self.rsp._parse_sexpr_edge_bounds(p1), (40.0, 60.0))

            p2 = pathlib.Path(td) / "poly.kicad_pcb"
            p2.write_text(pcb_poly, encoding="utf-8")
            self.assertEqual(self.rsp._parse_sexpr_edge_bounds(p2), (25.5, 100.25))

    def test_mm_to_px_and_back_round_trip_top_and_bottom(self) -> None:
        for side in ("top", "bottom"):
            for lx in (0.0, 7.5, 30.0):
                px = self.rsp._mm_to_px_x(lx, side, 10, 310, 30.0)
                rt = self.rsp._px_x_to_mm(px, side, 10, 310, 30.0)
                self.assertAlmostEqual(rt, lx, places=5)

    def test_draw_ruler_canvas_dimensions(self) -> None:
        img = Image.new("RGB", (400, 600), (28, 30, 34))
        out = self.rsp._draw_ruler_canvas(
            img,
            board_w=30.0,
            board_h=108.0,
            mm_x_left=0.0,
            mm_x_right=30.0,
            mm_y_top=0.0,
            mm_y_bottom=108.0,
            tick_step=10.0,
            title="BOTTOM (B.SilkS) - U1",
        )
        expected_w = self.rsp.MARGIN_LEFT + 400 + self.rsp.MARGIN_RIGHT
        expected_h = self.rsp.MARGIN_TOP + 600 + self.rsp.MARGIN_BOTTOM
        self.assertEqual(out.size, (expected_w, expected_h))
