from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest

HAS_PCBNEW = importlib.util.find_spec("pcbnew") is not None

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "packs/hardware/eurorack-panel/scripts"
if HAS_PCBNEW and str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


MINIMAL_PANEL_PCB = """(kicad_pcb
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(general
\t\t(thickness 1.6)
\t)
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(25 "Edge.Cuts" user)
\t)
\t(setup
\t\t(pad_to_mask_clearance 0)
\t)
\t(net 0 "")
\t(gr_rect
\t\t(start 100 40)
\t\t(end 120 168.5)
\t\t(stroke (width 0.05) (type solid))
\t\t(fill no)
\t\t(layer "Edge.Cuts")
\t)
\t(gr_text "BACK KEEP"
\t\t(at 110 100 0)
\t\t(layer "B.SilkS")
\t\t(effects (font (size 1 1) (thickness 0.15)) (justify mirror))
\t)
)"""


@unittest.skipUnless(HAS_PCBNEW, "requires KiCad pcbnew")
class ImportPanelSvgsKicadTests(unittest.TestCase):
    def setUp(self) -> None:
        import import_panel_svgs as ips

        self.ips = ips

    def test_parse_path_d_supports_arcs_with_compact_flags(self) -> None:
        subpaths = self.ips._parse_path_d("M10 10 A5 5 0 0120 10 A5 5 0 0110 10 Z")
        self.assertEqual(len(subpaths), 1)
        self.assertGreater(len(subpaths[0]), 16)

    def test_rounded_rect_produces_chamfered_corners(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="128.5mm" viewBox="0 0 20 128.5">
  <rect id="registration_frame" x="0" y="0" width="20" height="128.5" fill="none"/>
  <rect x="2" y="10" width="16" height="10" rx="2" ry="2" fill="#000000"/>
</svg>"""
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "rounded.svg"
            p.write_text(svg, encoding="utf-8")
            shapes = self.ips._parse_svg_shapes(p)
            self.assertEqual(len(shapes), 1)
            pts = shapes[0][1][0]
            self.assertGreater(len(pts), 20)
            # Sharp corner (2, 10) must not be present on a rounded rect.
            self.assertNotIn((2.0, 10.0), pts)

    def test_prunes_defs_hidden_fill_none_and_registration_frame(self) -> None:
        svg = """<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="128.5mm" viewBox="0 0 20 128.5">
  <defs><clipPath id="c"><rect x="1" y="1" width="5" height="5" fill="#000"/></clipPath></defs>
  <rect id="registration_frame" x="0" y="0" width="20" height="128.5" fill="#000"/>
  <g display="none"><rect x="2" y="2" width="4" height="4" fill="#000"/></g>
  <g fill="none"><rect x="3" y="3" width="4" height="4"/></g>
  <rect x="5" y="15" width="4" height="4" fill="#000"/>
</svg>"""
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "filter.svg"
            p.write_text(svg, encoding="utf-8")
            shapes = self.ips._parse_svg_shapes(p)
            self.assertEqual(len(shapes), 1)
            polysets = self.ips._shapes_to_polysets(shapes, 100.0, 40.0)
            self.assertEqual(len(polysets), 1)
            self.assertAlmostEqual(polysets[0].Area() / 1e12, 16.0, places=2)

    def test_nonzero_vs_evenodd_fill_rules(self) -> None:
        # Two overlapping same-winding rectangles: nonzero unions (area 150), evenodd XORs (area 100).
        d_overlap = "M0 0 H10 V10 H0 Z M5 0 H15 V10 H5 Z"
        # Outer CCW + inner CW hole + inner CCW island (bullseye): area = 100 - 36 + 4 = 68.
        d_bullseye = "M0 0 H10 V10 H0 Z M2 2 V8 H8 V2 Z M4 4 H6 V6 H4 Z"

        nz_overlap = self.ips._shapes_to_polysets(
            [("nonzero", self.ips._parse_path_d(d_overlap))], 0.0, 0.0
        )
        eo_overlap = self.ips._shapes_to_polysets(
            [("evenodd", self.ips._parse_path_d(d_overlap))], 0.0, 0.0
        )
        self.assertAlmostEqual(
            sum(ps.Area() for ps in nz_overlap) / 1e12, 150.0, places=1
        )
        self.assertAlmostEqual(
            sum(ps.Area() for ps in eo_overlap) / 1e12, 100.0, places=1
        )

        nz_bullseye = self.ips._shapes_to_polysets(
            [("nonzero", self.ips._parse_path_d(d_bullseye))], 0.0, 0.0
        )
        self.assertAlmostEqual(
            sum(ps.Area() for ps in nz_bullseye) / 1e12, 68.0, places=1
        )

    def test_does_not_mutate_pcb_when_svg_invalid_and_imports_idempotently(
        self,
    ) -> None:
        bad_svg = """<svg xmlns="http://www.w3.org/2000/svg">
  <g transform="translate(1 1)"><rect x="1" y="1" width="2" height="2" fill="#000"/></g>
</svg>"""
        good_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="128.5mm" viewBox="0 0 20 128.5">
  <rect id="registration_frame" x="0" y="0" width="20" height="128.5" fill="none"/>
  <rect x="4" y="20" width="12" height="4" rx="1" ry="1" fill="#000000"/>
</svg>"""
        with tempfile.TemporaryDirectory() as td:
            pcb_path = pathlib.Path(td) / "panel.kicad_pcb"
            pcb_path.write_text(MINIMAL_PANEL_PCB, encoding="utf-8")
            bad_path = pathlib.Path(td) / "bad.svg"
            bad_path.write_text(bad_svg, encoding="utf-8")
            good_path = pathlib.Path(td) / "good.svg"
            good_path.write_text(good_svg, encoding="utf-8")

            with self.assertRaises(ValueError):
                self.ips.import_panel_svgs(pcb_path, silks_svg=bad_path)
            self.assertEqual(pcb_path.read_text(encoding="utf-8"), MINIMAL_PANEL_PCB)

            stats1 = self.ips.import_panel_svgs(
                pcb_path, silks_svg=good_path, mask_svg=good_path
            )
            self.assertEqual(stats1["stackup_added"], 1)
            self.assertEqual(stats1["added_f_silks"], 1)
            self.assertEqual(stats1["added_f_mask"], 1)
            self.assertEqual(stats1["preserved_b_silks"], 1)

            stats2 = self.ips.import_panel_svgs(
                pcb_path, silks_svg=good_path, mask_svg=good_path
            )
            self.assertEqual(stats2["stackup_added"], 0)
            self.assertEqual(stats2["removed_f_silks"], 1)
            self.assertEqual(stats2["removed_f_mask"], 1)
            self.assertEqual(stats2["preserved_b_silks"], 1)
