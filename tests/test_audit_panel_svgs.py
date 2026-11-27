from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HAS_PIL_NUMPY = (
    importlib.util.find_spec("PIL") is not None
    and importlib.util.find_spec("numpy") is not None
)
if HAS_PIL_NUMPY:
    from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "packs/hardware/eurorack-panel/scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit_panel_svgs as aps


def _make_spec(width_mm: float = 20.0, height_mm: float = 128.5) -> dict:
    return {
        "canvas": {"width_mm": width_mm, "height_mm": height_mm},
        "mounting_slots": [],
        "components": [
            {
                "ref": "RV1",
                "kind": "pot",
                "local_x": 10.0,
                "local_y": 30.0,
                "drill_mm": 7.2,
                "keepout_mm": 11.0,
                "grounded": True,
            }
        ],
    }


class AuditPanelSvgsNormalizeTests(unittest.TestCase):
    def test_compact_arc_flags_scale_properly(self) -> None:
        scaled, pts = aps._scale_path_d("M10 10 A5 5 0 0120 20 Z", 2.0)
        self.assertIn("A10 10 0 0 1 40 40", scaled)
        self.assertEqual(pts[-1], (40.0, 40.0))

    def test_preserves_stroked_registration_frame_and_ignores_defs_hidden(self) -> None:
        w_mm, h_mm = 20.0, 128.5
        w_pt = w_mm / aps.PT_TO_MM
        h_pt = h_mm / aps.PT_TO_MM
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w_pt:.4f}pt" height="{h_pt:.4f}pt">
  <defs>
    <clipPath id="clip">
      <rect x="0" y="0" width="{w_pt:.4f}" height="{h_pt:.4f}" stroke="#ff0000"/>
    </clipPath>
  </defs>
  <g display="none">
    <rect x="1" y="1" width="5" height="5" stroke="#00ff00"/>
  </g>
  <rect x="0" y="0" width="{w_pt:.4f}" height="{h_pt:.4f}" fill="none" stroke="#ff0000" stroke-width="0.2"/>
  <rect x="10" y="20" width="10" height="5" fill="#112233"/>
  <rect x="10" y="30" width="10" height="5" fill="none"/>
</svg>"""
        with tempfile.TemporaryDirectory() as td:
            in_svg = pathlib.Path(td) / "raw.svg"
            out_svg = pathlib.Path(td) / "norm.svg"
            in_svg.write_text(svg, encoding="utf-8")
            stats = aps.normalize_svg_to_mm(in_svg, out_svg, "#000000", w_mm, h_mm)
            self.assertEqual(stats["stroked_nodes"], 0)
            self.assertEqual(stats["elements"], 3)

            root = ET.parse(out_svg).getroot()
            rects = [e for e in root.iter() if e.tag.split("}")[-1] == "rect"]
            # First rect is untouched inside <defs>, second inside display="none",
            # then reg frame, filled rect, and fill="none" rect.
            reg = [e for e in rects if e.attrib.get("id") == "registration_frame"]
            self.assertEqual(len(reg), 1)
            self.assertEqual(reg[0].attrib.get("fill"), "none")
            self.assertEqual(reg[0].attrib.get("stroke-width"), "0.05")
            self.assertEqual(rects[0].attrib.get("stroke"), "#ff0000")
            self.assertEqual(rects[1].attrib.get("stroke"), "#00ff00")
            self.assertEqual(rects[3].attrib.get("fill"), "#000000")
            self.assertEqual(rects[4].attrib.get("fill"), "none")

    def test_rejects_stroked_artwork_element(self) -> None:
        w_mm, h_mm = 20.0, 128.5
        w_pt = w_mm / aps.PT_TO_MM
        h_pt = h_mm / aps.PT_TO_MM
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="{w_pt:.4f}" height="{h_pt:.4f}" fill="none" stroke="#000"/>
  <path d="M10 10 L20 20" stroke="#000000" fill="none"/>
</svg>"""
        with tempfile.TemporaryDirectory() as td:
            in_svg = pathlib.Path(td) / "raw.svg"
            out_svg = pathlib.Path(td) / "norm.svg"
            in_svg.write_text(svg, encoding="utf-8")
            with self.assertRaises(RuntimeError):
                aps.normalize_svg_to_mm(in_svg, out_svg, "#000000", w_mm, h_mm)


@unittest.skipUnless(HAS_PIL_NUMPY, "requires Pillow and NumPy")
class AuditPanelSvgsBitmapTests(unittest.TestCase):
    def _canvas_px(self, spec: dict, px_per_mm: float = 10.0) -> tuple[int, int]:
        return (
            round(spec["canvas"]["width_mm"] * px_per_mm),
            round(spec["canvas"]["height_mm"] * px_per_mm),
        )

    def test_rgba_black_artwork_on_transparent_not_empty(self) -> None:
        spec = _make_spec()
        px_per_mm = 10.0
        w, h = self._canvas_px(spec, px_per_mm)
        with tempfile.TemporaryDirectory() as td:
            silks_p = pathlib.Path(td) / "silks.png"
            mask_p = pathlib.Path(td) / "mask.png"

            silks_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(silks_img).rectangle(
                [50, 700, 150, 750], fill=(0, 0, 0, 255)
            )
            silks_img.save(silks_p)

            mask_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(mask_img).rectangle(
                [50, 850, 150, 900], fill=(200, 155, 60, 255)
            )
            mask_img.save(mask_p)

            metrics = aps.run_clearance_audit(
                spec, silks_p, mask_p, px_per_mm=px_per_mm
            )
            self.assertGreater(metrics["silks_foreground_px"], 0)
            self.assertGreater(metrics["mask_foreground_px"], 0)
            self.assertGreaterEqual(metrics["silk_to_mask_min_gap_mm"], 0.2)

    def test_opaque_dark_on_light_auto_polarity_not_inverted(self) -> None:
        spec = _make_spec()
        px_per_mm = 10.0
        w, h = self._canvas_px(spec, px_per_mm)
        with tempfile.TemporaryDirectory() as td:
            silks_p = pathlib.Path(td) / "silks.png"
            mask_p = pathlib.Path(td) / "mask.png"

            silks_img = Image.new("RGB", (w, h), (255, 255, 255))
            ImageDraw.Draw(silks_img).rectangle([50, 700, 150, 750], fill=(0, 0, 0))
            silks_img.save(silks_p)

            mask_img = Image.new("RGB", (w, h), (255, 255, 255))
            ImageDraw.Draw(mask_img).rectangle([50, 850, 150, 900], fill=(0, 0, 0))
            mask_img.save(mask_p)

            metrics = aps.run_clearance_audit(
                spec, silks_p, mask_p, px_per_mm=px_per_mm
            )
            self.assertGreater(metrics["silks_foreground_px"], 0)
            self.assertLess(metrics["silks_foreground_px"], 10000)

    def test_empty_bitmap_fails_unless_allow_empty(self) -> None:
        spec = _make_spec()
        px_per_mm = 10.0
        w, h = self._canvas_px(spec, px_per_mm)
        with tempfile.TemporaryDirectory() as td:
            silks_p = pathlib.Path(td) / "silks.png"
            mask_p = pathlib.Path(td) / "mask.png"
            Image.new("RGBA", (w, h), (0, 0, 0, 0)).save(silks_p)
            mask_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(mask_img).rectangle(
                [50, 850, 150, 900], fill=(255, 255, 255, 255)
            )
            mask_img.save(mask_p)

            with self.assertRaisesRegex(RuntimeError, "empty"):
                aps.run_clearance_audit(spec, silks_p, mask_p, px_per_mm=px_per_mm)

            metrics = aps.run_clearance_audit(
                spec, silks_p, mask_p, px_per_mm=px_per_mm, allow_empty=True
            )
            self.assertEqual(metrics["silks_foreground_px"], 0)

    def test_binary_search_detects_close_silk_to_mask_gap(self) -> None:
        spec = _make_spec()
        px_per_mm = 10.0
        w, h = self._canvas_px(spec, px_per_mm)
        with tempfile.TemporaryDirectory() as td:
            silks_p = pathlib.Path(td) / "silks.png"
            mask_p = pathlib.Path(td) / "mask.png"

            silks_img = Image.new("RGB", (w, h), (0, 0, 0))
            ImageDraw.Draw(silks_img).rectangle(
                [50, 700, 150, 720], fill=(255, 255, 255)
            )
            silks_img.save(silks_p)

            # 1 px gap at 10 px/mm => 0.10 mm gap < 0.20 mm min
            mask_img = Image.new("RGB", (w, h), (0, 0, 0))
            ImageDraw.Draw(mask_img).rectangle(
                [50, 722, 150, 750], fill=(255, 255, 255)
            )
            mask_img.save(mask_p)

            with self.assertRaisesRegex(RuntimeError, "clearance too small"):
                aps.run_clearance_audit(spec, silks_p, mask_p, px_per_mm=px_per_mm)

    def test_pot_nut_keepout_enforced_by_default_and_skippable(self) -> None:
        spec = _make_spec()
        px_per_mm = 10.0
        w, h = self._canvas_px(spec, px_per_mm)
        with tempfile.TemporaryDirectory() as td:
            silks_p = pathlib.Path(td) / "silks.png"
            mask_p = pathlib.Path(td) / "mask.png"

            # Pot at (10, 30) mm => (100, 300) px; drill_zone radius = 3.85 mm (38.5 px),
            # nut_zone radius = 5.5 mm (55 px). Place silk at (145, 300) px (4.5 mm away).
            silks_img = Image.new("RGB", (w, h), (0, 0, 0))
            ImageDraw.Draw(silks_img).rectangle(
                [144, 298, 148, 302], fill=(255, 255, 255)
            )
            silks_img.save(silks_p)

            mask_img = Image.new("RGB", (w, h), (0, 0, 0))
            ImageDraw.Draw(mask_img).rectangle(
                [50, 850, 150, 900], fill=(255, 255, 255)
            )
            mask_img.save(mask_p)

            with self.assertRaisesRegex(RuntimeError, "RV1 nut keepout"):
                aps.run_clearance_audit(spec, silks_p, mask_p, px_per_mm=px_per_mm)

            metrics = aps.run_clearance_audit(
                spec,
                silks_p,
                mask_p,
                px_per_mm=px_per_mm,
                check_pot_nut_keepout=False,
            )
            self.assertNotIn("RV1_nut_silk_hits_px", metrics)
