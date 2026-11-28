from __future__ import annotations

import math
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

    def test_parse_netlist_jlcpcb_class_tht_and_dnp_and_show_ref(self) -> None:
        net = """(export (version "E")
\t(components
\t\t(comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric") (tstamp "00000000-0000-0000-0000-000000000001"))
\t\t(comp (ref "J_PWR") (value "PWR") (footprint "Connector_PinHeader_2.54mm:PinHeader_2x05_P2.54mm_Vertical")
\t\t\t(property (name "JLCPCB_Class") (value "Manual THT"))
\t\t\t(tstamp "00000000-0000-0000-0000-000000000002")
\t\t)
\t\t(comp (ref "TP1") (value "OUT") (footprint "TestPoint:TestPoint_Pad_D1.0mm")
\t\t\t(property (name "JLCPCB_Class") (value "DNP"))
\t\t\t(tstamp "00000000-0000-0000-0000-000000000003")
\t\t)
\t)
\t(nets
\t\t(net (code "1") (name "GND")
\t\t\t(node (ref "R1") (pin "1"))
\t\t)
\t)
)"""
        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            net_path = td_path / "test.net"
            net_path.write_text(net, encoding="utf-8")
            comps, _ = self.plt.parse_netlist(net_path)
            self.assertFalse(comps["R1"]["dnp"])
            self.assertFalse(comps["R1"]["exclude_from_pos_files"])
            self.assertFalse(comps["J_PWR"]["dnp"])
            self.assertFalse(comps["J_PWR"]["exclude_from_bom"])
            self.assertTrue(comps["J_PWR"]["exclude_from_pos_files"])
            self.assertTrue(comps["TP1"]["dnp"])
            self.assertTrue(comps["TP1"]["exclude_from_bom"])
            self.assertTrue(comps["TP1"]["exclude_from_pos_files"])

            pretty = td_path / "Custom.pretty"
            pretty.mkdir()
            fp_mod = """(footprint "Dummy"
\t(layer "F.Cu")
\t(fp_text reference "REF**" (at 0 0) (layer "F.SilkS"))
\t(fp_text value "Dummy" (at 0 1) (layer "F.Fab"))
)"""
            (pretty / "Dummy.kicad_mod").write_text(fp_mod, encoding="utf-8")
            b = self.plt.create_base_board(
                td_path / "b.kicad_pcb", 0.0, 0.0, 20.0, 20.0
            )
            mini_comp = {
                "R1": {
                    "ref": "R1",
                    "value": "10k",
                    "footprint": "Custom:Dummy",
                    "tstamp": "00000000-0000-0000-0000-000000000001",
                    "fields": {},
                    "dnp": False,
                    "exclude_from_bom": False,
                    "exclude_from_pos_files": False,
                }
            }
            fps = self.plt.populate_footprints(
                b,
                mini_comp,
                {"R1": (10.0, 10.0, 0.0, False)},
                custom_fp_dirs=[td_path],
                show_ref=False,
            )
            self.assertFalse(fps["R1"].Reference().IsVisible())
            self.assertEqual(fps["R1"].Reference().GetLayer(), pcbnew.F_Fab)

            fps_back = self.plt.populate_footprints(
                b,
                mini_comp,
                {"R1": (12.0, 12.0, 0.0, True)},
                custom_fp_dirs=[td_path],
                show_ref=False,
            )
            self.assertFalse(fps_back["R1"].Reference().IsVisible())
            self.assertEqual(fps_back["R1"].Reference().GetLayer(), pcbnew.B_Fab)

    def test_grid_router_exact_pad_box_via_margin_and_line_passable(self) -> None:
        router = self.plt.GridRouter(0.0, 0.0, 10.0, 10.0, step=0.25)
        router.mark_pad_box(0, 4.0, 4.0, 5.0, 5.0, 0.35, 1)
        corner_gx, corner_gy = router.to_grid(3.75, 3.75)
        edge_gx, edge_gy = router.to_grid(4.0, 3.75)
        self.assertEqual(router.pad_net[0][corner_gy * router.nx + corner_gx], -1)
        self.assertEqual(router.pad_net[0][edge_gy * router.nx + edge_gx], 1)

        router.mark_smd_via_block(2.0, 2.0, 3.0, 3.0)
        near_gx, near_gy = router.to_grid(3.25, 2.5)
        far_gx, far_gy = router.to_grid(7.0, 7.0)
        self.assertFalse(router.can_place_via(near_gx, near_gy, 1))
        self.assertTrue(router.can_place_via(far_gx, far_gy, 1))

        router.mark_via_block_circle(7.0, 7.0, 0.6)
        self.assertFalse(router.can_place_via(far_gx, far_gy, 1))
        self.assertTrue(router.is_passable(0, far_gx, far_gy, 1))

        fine_router = self.plt.GridRouter(0.0, 0.0, 6.0, 6.0, step=0.125)
        fine_router.mark_static_rect(0, 2.9, 2.9, 3.1, 3.1)
        # mark_static_rect snaps 2.9 down to 2.875; 0.375 mm away (< 0.50 mm) is blocked
        self.assertFalse(fine_router.can_place_via(*fine_router.to_grid(2.500, 3.0), 1))
        # 0.625 mm away (> 0.50 mm) must be allowed
        self.assertTrue(fine_router.can_place_via(*fine_router.to_grid(2.250, 3.0), 1))

        router.mark_static_rect(0, 5.9, 6.9, 6.1, 7.1)
        self.assertFalse(
            router.line_passable(
                0, *router.to_grid(5.0, 7.0), *router.to_grid(7.0, 7.0), 1
            )
        )
        self.assertTrue(
            router.line_passable(
                0, *router.to_grid(5.0, 8.0), *router.to_grid(7.0, 8.0), 1
            )
        )

    def test_route_and_pour_board_tht_via_exclusion_decoupling_and_offgrid_stubs(
        self,
    ) -> None:
        soic8_mod = """(footprint "SOIC8"
\t(layer "F.Cu")
\t(attr smd)
\t(fp_text reference "REF**" (at 0 -3) (layer "F.SilkS"))
\t(fp_text value "SOIC8" (at 0 3) (layer "F.Fab"))
\t(pad "1" smd rect (at -2.7 -1.905) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "2" smd rect (at -2.7 -0.635) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "3" smd rect (at -2.7 0.635) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "4" smd rect (at -2.7 1.905) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "5" smd rect (at 2.7 1.905) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "6" smd rect (at 2.7 0.635) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "7" smd rect (at 2.7 -0.635) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "8" smd rect (at 2.7 -1.905) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
)"""
        smd2_mod = """(footprint "SMD2"
\t(layer "F.Cu")
\t(attr smd)
\t(fp_text reference "REF**" (at 0 -1.5) (layer "F.SilkS"))
\t(fp_text value "SMD2" (at 0 1.5) (layer "F.Fab"))
\t(pad "1" smd rect (at -0.8 0) (size 0.9 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
\t(pad "2" smd rect (at 0.8 0) (size 0.9 0.9) (layers "F.Cu" "F.Paste" "F.Mask"))
)"""
        tht1_mod = """(footprint "THT1"
\t(layer "F.Cu")
\t(attr through_hole)
\t(fp_text reference "REF**" (at 0 -2) (layer "F.SilkS"))
\t(fp_text value "THT1" (at 0 2) (layer "F.Fab"))
\t(pad "1" thru_hole circle (at 0 0) (size 1.8 1.8) (drill 1.0) (layers "*.Cu" "*.Mask"))
)"""
        with tempfile.TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            pretty = td_path / "Custom.pretty"
            pretty.mkdir()
            (pretty / "SOIC8.kicad_mod").write_text(soic8_mod, encoding="utf-8")
            (pretty / "SMD2.kicad_mod").write_text(smd2_mod, encoding="utf-8")
            (pretty / "THT1.kicad_mod").write_text(tht1_mod, encoding="utf-8")

            board = self.plt.create_base_board(
                td_path / "routed.kicad_pcb", 0.0, 0.0, 40.0, 30.0
            )
            components = {
                ref: {
                    "ref": ref,
                    "value": val,
                    "footprint": fp_id,
                    "tstamp": f"00000000-0000-0000-0000-{idx:012d}",
                    "fields": {},
                    "dnp": False,
                    "exclude_from_bom": False,
                    "exclude_from_pos_files": False,
                }
                for idx, (ref, val, fp_id) in enumerate(
                    [
                        ("U1", "TL072", "Custom:SOIC8"),
                        ("C1", "100nF", "Custom:SMD2"),
                        ("C2", "100nF", "Custom:SMD2"),
                        ("R_BLK", "10k", "Custom:SMD2"),
                        ("R1", "10k", "Custom:SMD2"),
                        ("J1", "SIG", "Custom:THT1"),
                        ("J_GND", "GND", "Custom:THT1"),
                    ],
                    start=1,
                )
            }
            placements = {
                "U1": (12.0, 15.0, 0.0, True),
                "C1": (10.1, 10.5, 0.0, True),
                "C2": (9.3, 21.0, 0.0, True),
                "R_BLK": (9.3, 19.0, 0.0, True),
                "R1": (24.0, 15.0, 0.0, True),
                "J1": (32.11, 15.11, 0.0, False),
                "J_GND": (20.0, 22.0, 0.0, False),
            }
            fps = self.plt.populate_footprints(
                board, components, placements, custom_fp_dirs=[td_path]
            )
            nets = [
                {
                    "code": 1,
                    "name": "GND",
                    "nodes": [
                        ("C1", "2"),
                        ("C2", "2"),
                        ("R_BLK", "2"),
                        ("J_GND", "1"),
                    ],
                },
                {
                    "code": 2,
                    "name": "+12V",
                    "nodes": [("U1", "8"), ("C1", "1")],
                },
                {
                    "code": 3,
                    "name": "-12V",
                    "nodes": [("U1", "4"), ("C2", "1")],
                },
                {
                    "code": 4,
                    "name": "SIG1",
                    "nodes": [("U1", "1"), ("R1", "1")],
                },
                {
                    "code": 5,
                    "name": "SIG2",
                    "nodes": [("R1", "2"), ("J1", "1")],
                },
                {
                    "code": 6,
                    "name": "UNCONN_PIN",
                    "nodes": [("U1", "2")],
                },
                {
                    "code": 7,
                    "name": "BLK_NET",
                    "nodes": [("R_BLK", "1"), ("U1", "3")],
                },
            ]
            net_items, _ = self.plt.assign_nets(board, fps, nets)
            self.plt.route_and_pour_board(board, fps, net_items, 0.0, 0.0, 40.0, 30.0)

            tracks = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
            vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
            self.assertGreater(len(tracks), 0)
            self.assertEqual(len(board.Zones()), 2)
            for z in board.Zones():
                self.assertTrue(z.IsFilled())

            # 1-pin IC net must not leave dangling escape stubs
            self.assertEqual([t for t in tracks if t.GetNetname() == "UNCONN_PIN"], [])

            # No via may land inside any THT drill clearance radius (including J_GND)
            for via in vias:
                vp = via.GetPosition()
                vx, vy = pcbnew.ToMM(vp.x), pcbnew.ToMM(vp.y)
                self.assertGreater(math.hypot(vx - 20.0, vy - 22.0), 1.35)
                self.assertGreater(math.hypot(vx - 32.11, vy - 15.11), 1.35)

            # Off-grid J1 stub should only exist on layers actually used at J1's grid anchor
            j1_gx, j1_gy = 32.0, 15.0
            sig2_tracks = [t for t in tracks if t.GetNetname() == "SIG2"]
            stubs_at_j1 = []
            routed_layers_at_j1 = set()
            for tr in sig2_tracks:
                sx, sy = pcbnew.ToMM(tr.GetStart().x), pcbnew.ToMM(tr.GetStart().y)
                ex, ey = pcbnew.ToMM(tr.GetEnd().x), pcbnew.ToMM(tr.GetEnd().y)
                if (
                    math.hypot(sx - 32.11, sy - 15.11) < 0.02
                    and math.hypot(ex - j1_gx, ey - j1_gy) < 0.02
                ) or (
                    math.hypot(ex - 32.11, ey - 15.11) < 0.02
                    and math.hypot(sx - j1_gx, sy - j1_gy) < 0.02
                ):
                    stubs_at_j1.append(tr.GetLayer())
                elif (
                    math.hypot(sx - j1_gx, sy - j1_gy) < 0.02
                    or math.hypot(ex - j1_gx, ey - j1_gy) < 0.02
                ):
                    routed_layers_at_j1.add(tr.GetLayer())
            self.assertEqual(len(stubs_at_j1), 1)
            self.assertIn(stubs_at_j1[0], routed_layers_at_j1)
