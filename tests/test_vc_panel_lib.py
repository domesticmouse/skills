from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "packs/hardware/eurorack-brutalist-panel/scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import vc_panel_lib as vpl


def _make_sample_spec() -> dict:
    return {
        "canvas": {
            "width_mm": 30.0,
            "height_mm": 128.5,
            "rail_keepout_y_mm": {
                "top": [0.0, 8.0],
                "bottom": [120.5, 128.5],
            },
        },
        "fabrication_rules": {
            "copper_edge_pullback_mm": 0.60,
        },
        "mounting_slots": [
            {
                "ref": "H1",
                "local_x": 7.5,
                "local_y": 3.0,
                "width_mm": 5.0,
                "height_mm": 3.2,
            }
        ],
        "components": [
            {
                "ref": "RV1",
                "kind": "pot",
                "local_x": 15.0,
                "local_y": 32.0,
                "drill_mm": 7.2,
                "keepout_mm": 11.0,
                "max_knob_mm": 14.0,
                "grounded": True,
            },
            {
                "ref": "J1",
                "kind": "jack",
                "local_x": 15.0,
                "local_y": 95.0,
                "drill_mm": 6.2,
                "keepout_mm": 9.5,
                "grounded": True,
            },
            {
                "ref": "D1",
                "kind": "led_3mm",
                "local_x": 22.0,
                "local_y": 60.0,
                "drill_mm": 3.2,
                "keepout_mm": 5.5,
                "grounded": False,
            },
        ],
    }


class VcPanelLibHelperTests(unittest.TestCase):
    def test_pt_conversion(self) -> None:
        self.assertEqual(vpl.pt(0.0), 0.0)
        self.assertEqual(vpl.pt(25.4), 72.0)
        self.assertEqual(vpl.pt(12.7), 36.0)
        self.assertEqual(vpl.pt(1.0), round(72.0 / 25.4, 6))

    def test_load_panel_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_md = pathlib.Path(td) / "panel_svg_spec.md"
            spec_md.write_text(
                '# Panel Spec\n\n```json\n{"canvas": {"width_mm": 30.0}}\n```\n',
                encoding="utf-8",
            )
            parsed = vpl.load_panel_spec(spec_md)
            self.assertEqual(parsed["canvas"]["width_mm"], 30.0)

            bad_md = pathlib.Path(td) / "missing_json.md"
            bad_md.write_text("# No JSON here\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                vpl.load_panel_spec(bad_md)

    def test_chamfer_rect_points(self) -> None:
        plain = vpl.chamfer_rect_points(0.0, 0.0, 10.0, 5.0)
        self.assertEqual(plain, [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0)])

        tr_bl = vpl.chamfer_rect_points(0.0, 0.0, 10.0, 5.0, tr=1.5, bl=1.5)
        self.assertEqual(len(tr_bl), 6)
        self.assertEqual(
            tr_bl,
            [
                (0.0, 0.0),
                (8.5, 0.0),
                (10.0, 1.5),
                (10.0, 5.0),
                (1.5, 5.0),
                (0.0, 3.5),
            ],
        )

        tl_br = vpl.chamfer_rect_points(0.0, 0.0, 10.0, 5.0, tl=1.0, br=1.0)
        self.assertEqual(len(tl_br), 6)
        self.assertEqual(
            tl_br,
            [
                (0.0, 1.0),
                (1.0, 0.0),
                (10.0, 0.0),
                (10.0, 4.0),
                (9.0, 5.0),
                (0.0, 5.0),
            ],
        )

        all_four = vpl.chamfer_rect_points(
            0.0, 0.0, 10.0, 5.0, tl=1.0, tr=1.0, br=1.0, bl=1.0
        )
        self.assertEqual(len(all_four), 8)

        touching = vpl.chamfer_rect_points(
            0.0, 0.0, 4.0, 4.0, tl=2.0, tr=2.0, br=2.0, bl=2.0
        )
        self.assertEqual(touching, [(0.0, 2.0), (2.0, 0.0), (4.0, 2.0), (2.0, 4.0)])

        for bad_args in (
            (10.0, 0.0, 10.0, 5.0),
            (0.0, 5.0, 10.0, 2.0),
            (0.0, 0.0, 10.0, 5.0, -1.0),
            (0.0, 0.0, 10.0, 5.0, 6.0, 5.0),
            (0.0, 0.0, 10.0, 5.0, 3.0, 0.0, 0.0, 3.0),
        ):
            with self.assertRaises(ValueError):
                vpl.chamfer_rect_points(*bad_args)

    def test_regular_polygon_points(self) -> None:
        pts = vpl.regular_polygon_points(5.0, 10.0, 3.0, 8, rot_deg=22.5)
        self.assertEqual(len(pts), 8)
        for x, y in pts:
            self.assertAlmostEqual(((x - 5.0) ** 2 + (y - 10.0) ** 2) ** 0.5, 3.0)

        pts_zero = vpl.regular_polygon_points(0.0, 0.0, 2.0, 4, rot_deg=0.0)
        pts_rot = vpl.regular_polygon_points(0.0, 0.0, 2.0, 4, rot_deg=45.0)
        self.assertAlmostEqual(pts_zero[0][0], 2.0)
        self.assertAlmostEqual(pts_zero[0][1], 0.0)
        self.assertAlmostEqual(pts_rot[0][0], 2.0 * (2.0**0.5) / 2.0)
        self.assertAlmostEqual(pts_rot[0][1], 2.0 * (2.0**0.5) / 2.0)

        for bad_radius, bad_sides in ((3.0, 2), (3.0, 0), (0.0, 6), (-1.0, 6)):
            with self.assertRaises(ValueError):
                vpl.regular_polygon_points(0.0, 0.0, bad_radius, bad_sides)


class StepBuilderTests(unittest.TestCase):
    def test_step_builder_commands(self) -> None:
        sb = vpl.StepBuilder()
        lyr = sb.new_layer("01_F_Mask_Gold", "#d8b154")
        self.assertEqual(lyr, "$0.id")
        sb.set_current_layer(lyr)
        sb.set_layer_visible(lyr, False)

        r1 = sb.rect_fill(1.0, 2.0, 4.0, 3.0, "#ffffff")
        self.assertEqual(sb.steps[3]["command"], "shape.rectangle")
        self.assertNotIn("radius", sb.steps[3]["params"])
        self.assertNotIn("rotation", sb.steps[3]["params"])
        self.assertEqual(r1, "$3.id")

        sb.rect_fill(1.0, 2.0, 4.0, 3.0, "#ffffff", radius_mm=0.5, rotation_deg=45.0)
        self.assertIn("radius", sb.steps[6]["params"])
        self.assertEqual(sb.steps[6]["params"]["rotation"], 45.0)

        rs = sb.rect_stroke_outlined(
            0.0, 0.0, 10.0, 5.0, 0.5, "#d8b154", align="inside"
        )
        self.assertTrue(rs.endswith(".ids[0]"))
        self.assertEqual(sb.steps[-1]["command"], "object.path.outlineStroke")

        c1 = sb.circle_fill(5.0, 5.0, 3.2, "#07080a")
        self.assertEqual(sb.steps[-3]["command"], "shape.ellipse")
        self.assertTrue(c1.endswith(".id"))

        p1 = sb.polygon_fill([(0.0, 0.0), (2.0, 0.0), (1.0, 2.0)], "#d8b154")
        self.assertEqual(sb.steps[-3]["command"], "path.create")
        self.assertTrue(p1.endswith(".id"))

        ps = sb.polygon_stroke_outlined(
            [(0.0, 0.0), (2.0, 0.0)], 0.3, "#ffffff", closed=False
        )
        self.assertTrue(ps.endswith(".ids[0]"))

        ls = sb.line_stroke_outlined(0.0, 0.0, 10.0, 0.0, 0.24, "#ffffff")
        self.assertTrue(ls.endswith(".ids[0]"))
        self.assertEqual(sb.steps[-5]["command"], "shape.line")

        t1 = sb.text_outlined(5.0, 10.0, "OUT", "DIN Alternate", "Bold", 2.0, "#000000")
        self.assertTrue(t1.endswith(".ids[0]"))
        self.assertEqual(sb.steps[-2]["command"], "text.create")
        self.assertEqual(sb.steps[-1]["command"], "type.createOutlines")

        t2 = sb.text_outlined(
            5.0, 14.0, "ENV", "DIN Condensed", "Bold", 3.0, "#000000", tracking=25
        )
        self.assertTrue(t2.endswith(".ids[0]"))
        self.assertEqual(sb.steps[-2]["command"], "text.setStyle")
        self.assertEqual(sb.steps[-2]["params"]["tracking"], 25)

        mf = sb.minus_front(r1, t1)
        self.assertEqual(sb.steps[-1]["command"], "object.pathfinder.minusFront")
        self.assertEqual(sb.steps[-1]["params"]["ids"], [r1, t1])
        self.assertTrue(mf.endswith(".ids[0]"))

        with tempfile.TemporaryDirectory() as td:
            out_path = pathlib.Path(td) / "nested" / "build_steps.json"
            written = sb.write_commands(out_path)
            self.assertEqual(written, out_path)
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, sb.steps)


class DocumentPipelineTests(unittest.TestCase):
    def test_minimal_spec_tolerates_missing_optional_collections(self) -> None:
        minimal_spec = {"canvas": {"width_mm": 20.0, "height_mm": 128.5}}
        sb = vpl.StepBuilder()
        layers = vpl.init_panel_document(sb, minimal_spec, "Minimal Panel")
        vpl.populate_mockup_layer(sb, layers["mockup"], minimal_spec)
        vpl.populate_keepout_layer(sb, layers["keepout"], minimal_spec)
        self.assertTrue(any(s["command"] == "shape.rectangle" for s in sb.steps))

    def test_full_pipeline_builds_standard_layers_and_exports(self) -> None:
        spec = _make_sample_spec()
        sb = vpl.StepBuilder()
        layers = vpl.init_panel_document(sb, spec, "Test Brutalist Panel")

        self.assertEqual(
            set(layers.keys()), {"mockup", "mask", "silks", "reg", "keepout"}
        )
        self.assertEqual(sb.steps[0]["command"], "file.new")
        self.assertEqual(sb.steps[0]["params"]["units"], "Millimeters")
        self.assertEqual(sb.steps[0]["params"]["width"], "30.0 mm")
        self.assertEqual(sb.steps[0]["params"]["height"], "128.5 mm")

        vpl.populate_mockup_layer(sb, layers["mockup"], spec)
        vpl.populate_registration_layer(sb, layers["reg"], spec)
        vpl.populate_keepout_layer(sb, layers["keepout"], spec)

        # Simulate caller toggling artwork layers hidden before exports.
        for key in ("mockup", "mask", "silks"):
            sb.set_layer_visible(layers[key], False)

        vpl.append_standard_exports(
            sb, layers, pathlib.Path("panel_art"), vc_stem="test_panel"
        )

        commands = [s["command"] for s in sb.steps]
        self.assertNotIn("text.fontList", commands)

        ref_to_name = {ref: name for name, ref in layers.items()}
        visible_state = {name: True for name in layers}
        visibility_at_export: dict[str, set[str]] = {}
        for step in sb.steps:
            cmd = step["command"]
            params = step.get("params", {})
            if cmd == "layer.setProps" and "visible" in params:
                visible_state[ref_to_name[params["id"]]] = bool(params["visible"])
            elif cmd == "document.export":
                name = pathlib.Path(params["path"]).name
                visibility_at_export[name] = {
                    k for k, is_vis in visible_state.items() if is_vis
                }

        self.assertEqual(
            visibility_at_export,
            {
                "test_panel.vectorcraft": {"mockup", "mask", "silks"},
                "preview_clean.png": {"mockup", "mask", "silks"},
                "preview_keepouts.png": {"mockup", "mask", "silks", "keepout"},
                "front_silkscreen.raw.svg": {"silks", "reg"},
                "front_soldermask.raw.svg": {"mask", "reg"},
                "_audit_silks.png": {"silks"},
                "_audit_mask.png": {"mask"},
            },
        )

        exports = [s["params"] for s in sb.steps if s["command"] == "document.export"]
        export_paths = [e["path"] for e in exports]
        self.assertEqual(
            export_paths,
            [
                "panel_art/test_panel.vectorcraft",
                "panel_art/preview_clean.png",
                "panel_art/preview_keepouts.png",
                "panel_art/front_silkscreen.raw.svg",
                "panel_art/front_soldermask.raw.svg",
                "panel_art/_audit_silks.png",
                "panel_art/_audit_mask.png",
            ],
        )
        audit_silks = next(e for e in exports if e["path"].endswith("_audit_silks.png"))
        audit_mask = next(e for e in exports if e["path"].endswith("_audit_mask.png"))
        for audit_export in (audit_silks, audit_mask):
            self.assertEqual(audit_export["ppi"], 1016.0)
            self.assertEqual(audit_export["background"], "black")
            self.assertEqual(audit_export["antiAlias"], "none")


if __name__ == "__main__":
    unittest.main()
