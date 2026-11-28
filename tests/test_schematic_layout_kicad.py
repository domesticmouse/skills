from __future__ import annotations

import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCH_SCRIPT_DIR = ROOT / "packs/hardware/kicad-schematic-layout/scripts"
if str(SCH_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCH_SCRIPT_DIR))

import inspect_schematic_inputs as isi
import sch_builder as sb_mod

HAS_KICAD_SYMBOLS = sb_mod._default_symbol_dir().is_dir()
KICAD_CLI = sb_mod._default_kicad_cli()
HAS_KICAD_CLI = KICAD_CLI.is_file() or bool(
    subprocess.run(
        ["which", str(KICAD_CLI)], capture_output=True, check=False
    ).returncode
    == 0
)


class SchematicBuilderUnitTests(unittest.TestCase):
    def test_pin_world_transforms_and_combined_guard(self) -> None:
        self.assertEqual(
            sb_mod.pin_world(100.0, 100.0, 0, None, 2.54, 5.08), (102.54, 94.92)
        )
        self.assertEqual(
            sb_mod.pin_world(100.0, 100.0, 90, None, 0.0, 3.81), (96.19, 100.0)
        )
        self.assertEqual(
            sb_mod.pin_world(100.0, 100.0, 180, None, 0.0, 3.81), (100.0, 103.81)
        )
        self.assertEqual(
            sb_mod.pin_world(100.0, 100.0, 270, None, 0.0, 3.81), (103.81, 100.0)
        )
        self.assertEqual(
            sb_mod.pin_world(100.0, 100.0, 0, "x", -7.62, 2.54), (92.38, 102.54)
        )
        self.assertEqual(
            sb_mod.pin_world(100.0, 100.0, 0, "y", 5.08, 2.54), (94.92, 97.46)
        )

        with self.assertRaises(ValueError):
            sb_mod.pin_world(100.0, 100.0, 90, "x", 0.0, 0.0)

    @unittest.skipUnless(HAS_KICAD_SYMBOLS, "requires KiCad 10 symbol libraries")
    def test_load_kicad10_symbol_flattens_extends(self) -> None:
        flat_npn, npn_pins = sb_mod.load_kicad10_symbol("Transistor_BJT", "BC848")
        self.assertEqual(str(flat_npn[1]), "Transistor_BJT:BC848")
        self.assertIsNone(sb_mod._find_child(flat_npn, "extends"))
        self.assertEqual({p.name for p in npn_pins[1]}, {"B", "C", "E"})

        flat_opamp, op_pins = sb_mod.load_kicad10_symbol(
            "Amplifier_Operational", "TL074"
        )
        self.assertEqual(str(flat_opamp[1]), "Amplifier_Operational:TL074")
        self.assertIsNone(sb_mod._find_child(flat_opamp, "extends"))
        self.assertEqual(sorted(op_pins.keys()), [1, 2, 3, 4, 5])

    @unittest.skipUnless(
        HAS_KICAD_SYMBOLS and HAS_KICAD_CLI,
        "requires KiCad 10 symbol libraries and kicad-cli",
    )
    def test_build_verify_and_inspect_end_to_end(self) -> None:
        net_text = """(export
  (version "D")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric")
      (libsource (lib "Device") (part "R")))
    (comp (ref "C1") (value "100nF") (footprint "Capacitor_SMD:C_0603_1608Metric")
      (libsource (lib "Device") (part "C")))
    (comp (ref "Q1") (value "BC848B") (footprint "Package_TO_SOT_SMD:SOT-23")
      (libsource (lib "Transistor_BJT") (part "BC848")))
    (comp (ref "U1") (value "TL072") (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
      (libsource (lib "Amplifier_Operational") (part "TL072")))
  )
  (nets
    (net (code "1") (name "+12V")
      (node (ref "R1") (pin "1"))
      (node (ref "Q1") (pin "3"))
      (node (ref "U1") (pin "8")))
    (net (code "2") (name "GND")
      (node (ref "C1") (pin "2"))
      (node (ref "Q1") (pin "2"))
      (node (ref "U1") (pin "3"))
      (node (ref "U1") (pin "5")))
    (net (code "3") (name "-12V")
      (node (ref "U1") (pin "4")))
    (net (code "4") (name "BASE")
      (node (ref "R1") (pin "2"))
      (node (ref "C1") (pin "1"))
      (node (ref "Q1") (pin "1"))
      (node (ref "U1") (pin "1"))
      (node (ref "U1") (pin "2")))
    (net (code "5") (name "BUF_B")
      (node (ref "U1") (pin "6"))
      (node (ref "U1") (pin "7")))
  )
)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            net_path = tmp / "mini.net"
            sch_path = tmp / "mini.kicad_sch"
            net_path.write_text(net_text, encoding="utf-8")

            meta = sb_mod.load_netlist_parts_metadata(net_path)
            sb = sb_mod.SchematicBuilder("mini", meta, paper="A3", title="MINI TEST")
            sb.place(
                "R1",
                96.52,
                81.28,
                angle=90,
                ref_offset=(0, -3.81),
                ref_justify="center",
            )
            sb.place("C1", 104.14, 96.52, angle=0)
            sb.place("Q1", 119.38, 81.28, angle=0)
            sb.place("U1", 142.24, 81.28, mirror="x", unit=1)
            sb.place("U1", 142.24, 104.14, mirror="x", unit=2)
            sb.place("U1", 81.28, 121.92, angle=0, unit=3)

            # +12V bus + PWR_FLAG
            sb.power("+12V", 88.9, 68.58, pwr_flag=True)
            sb.wire((88.9, 68.58), (88.9, 81.28), sb.pin("R1", 1))
            sb.wire((88.9, 68.58), (121.92, 68.58), sb.pin("Q1", "C"))
            sb.power("+12V", 78.74, 111.76)
            sb.wire(sb.pin("U1", 8, unit=3), (78.74, 111.76))

            # -12V + PWR_FLAG
            sb.power("-12V", 78.74, 132.08, angle=180, pwr_flag=True)
            sb.wire(sb.pin("U1", 4, unit=3), (78.74, 132.08))

            # GND + PWR_FLAG
            sb.power("GND", 104.14, 104.14, pwr_flag=True)
            sb.wire(sb.pin("C1", 2), (104.14, 104.14))
            sb.power("GND", 121.92, 91.44)
            sb.wire(sb.pin("Q1", "E"), (121.92, 91.44))
            sb.power("GND", 132.08, 91.44)
            sb.wire_hv(sb.pin("U1", 3, unit=1), (132.08, 91.44))
            sb.power("GND", 132.08, 114.3)
            sb.wire_hv(sb.pin("U1", 5, unit=2), (132.08, 114.3))

            # BASE net with T-junction at (104.14, 81.28) and corner at (149.86, 73.66)
            sb.wire(sb.pin("R1", 2), (104.14, 81.28), sb.pin("Q1", "B"))
            sb.wire(sb.pin("C1", 1), (104.14, 81.28))
            sb.wire(
                sb.pin("U1", 2, unit=1),
                (132.08, 78.74),
                (132.08, 73.66),
                (114.3, 73.66),
            )
            sb.wire((114.3, 73.66), (114.3, 81.28))
            sb.wire(sb.pin("U1", 1, unit=1), (149.86, 73.66), (132.08, 73.66))

            # Unit 2 follower feedback
            sb.wire(
                sb.pin("U1", 6, unit=2),
                (132.08, 101.6),
                (132.08, 96.52),
                (149.86, 96.52),
                sb.pin("U1", 7, unit=2),
            )

            sb.write(sch_path)
            content = sch_path.read_text(encoding="utf-8")
            self.assertNotIn("(justify center)", content)

            # Verify corner (149.86, 73.66) did NOT get a junction, while 3-wire T (104.14, 81.28)
            # and 2-wire + pin T (88.9, 68.58) DID get junctions.
            junctions = sb._compute_junctions()
            self.assertIn((104.14, 81.28), junctions)
            self.assertIn((88.9, 68.58), junctions)
            self.assertNotIn((149.86, 73.66), junctions)

            # Verify ERC & netlist equivalence (4 multi-pin + 1 single-pin -12V = 5 nets)
            summary = sb_mod.verify_schematic(sch_path, net_path)
            self.assertEqual(summary["components"], 4)
            self.assertEqual(summary["multi_pin_nets"], 4)
            self.assertEqual(summary["single_pin_nets"], 1)
            self.assertEqual(summary["total_nets"], 5)
            rc = isi._verify_schematic(sch_path, net_path, KICAD_CLI)
            self.assertEqual(rc, 0)

    def test_load_netlist_parts_metadata_dnp_and_standard_fields(self) -> None:
        net_text = """(export
  (version "D")
  (components
    (comp (ref "TP1") (value "TP_IN") (footprint "TestPoint:TestPoint_Pad_D1.0mm")
      (fields
        (field (name "Footprint") "TestPoint:TestPoint_Pad_D1.0mm")
        (field (name "Datasheet") "~")
        (field (name "Description") "test point")
        (field (name "LCSC") "C5199801")
      )
      (libsource (lib "Connector") (part "TestPoint"))
      (property (name "dnp"))
      (property (name "exclude_from_bom"))
      (property (name "exclude_from_pos_files"))
    )
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric")
      (fields (field (name "MPN") "RC0603FR-0710KL"))
      (libsource (lib "Device") (part "R"))
      (properties
        (property (name "dnp") (value "yes"))
        (property (name "exclude_from_bom") (value "1"))
      )
    )
  )
  (nets)
)"""
        with tempfile.TemporaryDirectory() as td:
            net_path = pathlib.Path(td) / "parts.net"
            net_path.write_text(net_text, encoding="utf-8")
            meta = sb_mod.load_netlist_parts_metadata(net_path)

        self.assertTrue(meta["TP1"].dnp)
        self.assertTrue(meta["TP1"].exclude_from_bom)
        self.assertTrue(meta["TP1"].exclude_from_pos_files)
        self.assertEqual(meta["TP1"].fields, {"LCSC": "C5199801"})

        self.assertTrue(meta["R1"].dnp)
        self.assertTrue(meta["R1"].exclude_from_bom)
        self.assertFalse(meta["R1"].exclude_from_pos_files)
        self.assertEqual(meta["R1"].fields, {"MPN": "RC0603FR-0710KL"})

        if HAS_KICAD_SYMBOLS:
            b = sb_mod.SchematicBuilder("parts", meta)
            b.place("TP1", 50.8, 50.8)
            placed_sexp = sb_mod._format_sexp(b._symbol_nodes[0])
            self.assertEqual(placed_sexp.count('(property "Footprint"'), 1)
            self.assertEqual(placed_sexp.count('(property "Datasheet"'), 1)
            self.assertEqual(placed_sexp.count('(property "Description"'), 1)
            self.assertIn('(property "LCSC" "C5199801"', placed_sexp)
            self.assertIn("(in_bom no)", placed_sexp)
            self.assertIn("(on_board no)", placed_sexp)
            self.assertIn("(dnp yes)", placed_sexp)

    @unittest.skipUnless(HAS_KICAD_SYMBOLS, "requires KiCad 10 symbol libraries")
    def test_place_orientations_justify_and_duplicate_guard(self) -> None:
        meta = {
            "R1": sb_mod.PartMetadata(
                ref="R1",
                lib_id="Device:R",
                value="10k",
                footprint="Resistor_SMD:R_0603_1608Metric",
                fields={"Footprint": "dup_ignored", "LCSC": "C1"},
            ),
            "R2": sb_mod.PartMetadata(
                ref="R2",
                lib_id="Device:R",
                value="22k",
                footprint="Resistor_SMD:R_0603_1608Metric",
            ),
            "R3": sb_mod.PartMetadata(
                ref="R3",
                lib_id="Device:R",
                value="47k",
                footprint="Resistor_SMD:R_0603_1608Metric",
            ),
        }
        b = sb_mod.SchematicBuilder("orient", meta)
        b.place("R1", 50.8, 50.8, angle=90, ref_justify="left", val_justify="right")
        b.place("R2", 76.2, 50.8, mirror="y", ref_justify="left", val_justify="right")
        b.place(
            "R3",
            101.6,
            50.8,
            angle=90,
            prop_angle=0,
            ref_justify="left",
            val_justify="right",
        )
        with self.assertRaises(ValueError):
            b.place("R1", 50.8, 63.5)

        b.no_connect((50.8, 54.61))
        b.no_connect((50.8, 54.61))
        b.label("SIG_OUT", 101.6, 46.99, justify="center left")

        sexp = b.to_sexp_str()
        placed_sexp = "\n".join(sb_mod._format_sexp(n) for n in b._symbol_nodes)
        self.assertNotIn("fields_autoplaced", placed_sexp)
        self.assertNotIn("(justify center)", sexp)
        self.assertEqual(len(b._no_connects), 1)
        self.assertEqual(sexp.count("(no_connect\n"), 1)
        self.assertEqual(placed_sexp.count('(property "Footprint"'), 3)
        self.assertIn('(label "SIG_OUT"\n    (at 101.6 46.99 0)', sexp)

        # Verify R1 (angle=90) and R2 (mirror="y") flipped left<->right, while R3 (prop_angle=0) did not
        r1_node = b._symbol_nodes[0]
        r2_node = b._symbol_nodes[1]
        r3_node = b._symbol_nodes[2]
        r1_ref_eff = sb_mod._find_child(
            next(
                p
                for p in sb_mod._find_children(r1_node, "property")
                if p[1] == "Reference"
            ),
            "effects",
        )
        r2_ref_eff = sb_mod._find_child(
            next(
                p
                for p in sb_mod._find_children(r2_node, "property")
                if p[1] == "Reference"
            ),
            "effects",
        )
        r3_ref_eff = sb_mod._find_child(
            next(
                p
                for p in sb_mod._find_children(r3_node, "property")
                if p[1] == "Reference"
            ),
            "effects",
        )
        self.assertEqual(
            sb_mod._find_child(r1_ref_eff, "justify"), ["justify", "right"]
        )
        self.assertEqual(
            sb_mod._find_child(r2_ref_eff, "justify"), ["justify", "right"]
        )
        self.assertEqual(sb_mod._find_child(r3_ref_eff, "justify"), ["justify", "left"])

    @unittest.skipUnless(HAS_KICAD_SYMBOLS, "requires KiCad 10 symbol libraries")
    def test_power_orientation_and_flags(self) -> None:
        b = sb_mod.SchematicBuilder("pwr", {})
        b.power("+12V", 50.8, 50.8, angle=90, val_justify="left", pwr_flag=True)
        b.power("GND", 76.2, 50.8, angle=180, val_justify="right")
        b.power("-12V", 101.6, 50.8, angle=270, val_justify="left")
        with self.assertRaises(ValueError):
            b.power("GND", 50.8, 63.5, angle=45)

        placed_sexp = "\n".join(sb_mod._format_sexp(n) for n in b._symbol_nodes)
        self.assertNotIn("(in_bom yes)", placed_sexp)
        self.assertNotIn("(on_board yes)", placed_sexp)

        p90_val = next(
            p
            for p in sb_mod._find_children(b._symbol_nodes[0], "property")
            if p[1] == "Value"
        )
        self.assertEqual(sb_mod._find_child(p90_val, "at")[3], "90")
        self.assertEqual(
            sb_mod._find_child(sb_mod._find_child(p90_val, "effects"), "justify"),
            ["justify", "right"],
        )

        gnd180_val = next(
            p
            for p in sb_mod._find_children(b._symbol_nodes[2], "property")
            if p[1] == "Value"
        )
        self.assertEqual(sb_mod._find_child(gnd180_val, "at")[3], "0")
        self.assertEqual(
            sb_mod._find_child(sb_mod._find_child(gnd180_val, "effects"), "justify"),
            ["justify", "left"],
        )

        m270_val = next(
            p
            for p in sb_mod._find_children(b._symbol_nodes[3], "property")
            if p[1] == "Value"
        )
        self.assertEqual(sb_mod._find_child(m270_val, "at")[3], "90")
        self.assertEqual(
            sb_mod._find_child(sb_mod._find_child(m270_val, "effects"), "justify"),
            ["justify", "left"],
        )

    @unittest.skipUnless(
        HAS_KICAD_SYMBOLS and HAS_KICAD_CLI,
        "requires KiCad 10 symbol libraries and kicad-cli",
    )
    def test_verify_schematic_catches_warnings_and_single_pin_rail_mismatch(
        self,
    ) -> None:
        net_text = """(export
  (version "D")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric")
      (libsource (lib "Device") (part "R")))
    (comp (ref "U1") (value "TL072") (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
      (libsource (lib "Amplifier_Operational") (part "TL072")))
  )
  (nets
    (net (code "1") (name "+12V")
      (node (ref "R1") (pin "1"))
      (node (ref "U1") (pin "8")))
    (net (code "2") (name "-12V")
      (node (ref "U1") (pin "4")))
    (net (code "3") (name "GND")
      (node (ref "R1") (pin "2"))
      (node (ref "U1") (pin "3"))
      (node (ref "U1") (pin "5")))
    (net (code "4") (name "OUT_A")
      (node (ref "U1") (pin "1"))
      (node (ref "U1") (pin "2")))
    (net (code "5") (name "OUT_B")
      (node (ref "U1") (pin "6"))
      (node (ref "U1") (pin "7")))
  )
)"""
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            net_path = tmp / "rail.net"
            net_path.write_text(net_text, encoding="utf-8")
            meta = sb_mod.load_netlist_parts_metadata(net_path)

            def build_base(
                neg_rail: str, *, dangling_wire: bool = False
            ) -> pathlib.Path:
                b = sb_mod.SchematicBuilder("rail", meta)
                b.place("R1", 50.8, 50.8, angle=0)
                b.place("U1", 88.9, 50.8, mirror="x", unit=1)
                b.place("U1", 88.9, 76.2, mirror="x", unit=2)
                b.place("U1", 50.8, 88.9, angle=0, unit=3)

                b.power("+12V", 50.8, 40.64, pwr_flag=True)
                b.wire(b.pin("R1", 1), (50.8, 40.64))
                b.power("+12V", 48.26, 76.2)
                b.wire(b.pin("U1", 8, unit=3), (48.26, 76.2))

                b.power(neg_rail, 48.26, 101.6, angle=180, pwr_flag=True)
                b.wire(b.pin("U1", 4, unit=3), (48.26, 101.6))

                b.power("GND", 50.8, 60.96, pwr_flag=True)
                b.wire(b.pin("R1", 2), (50.8, 60.96))
                b.power("GND", 76.2, 60.96)
                b.wire_hv(b.pin("U1", 3, unit=1), (76.2, 60.96))
                b.power("GND", 76.2, 86.36)
                b.wire_hv(b.pin("U1", 5, unit=2), (76.2, 86.36))

                b.wire(
                    b.pin("U1", 2, unit=1),
                    (78.74, 48.26),
                    (78.74, 43.18),
                    (96.52, 43.18),
                    b.pin("U1", 1, unit=1),
                )
                b.wire(
                    b.pin("U1", 6, unit=2),
                    (78.74, 73.66),
                    (78.74, 68.58),
                    (96.52, 68.58),
                    b.pin("U1", 7, unit=2),
                )
                if dangling_wire:
                    b.wire((127.0, 50.8), (139.7, 50.8))
                out = tmp / f"sch_{neg_rail}_{dangling_wire}.kicad_sch"
                b.write(out)
                return out

            # 1. Single-pin rail mismatch (-5V instead of -12V) must fail
            wrong_rail_sch = build_base("-5V")
            with self.assertRaises(RuntimeError):
                sb_mod.verify_schematic(wrong_rail_sch, net_path)
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with (
                contextlib.redirect_stdout(out_buf),
                contextlib.redirect_stderr(err_buf),
            ):
                rc_rail = isi._verify_schematic(wrong_rail_sch, net_path, KICAD_CLI)
            self.assertEqual(rc_rail, 1)
            self.assertNotIn("PASS:", out_buf.getvalue())

            # 2. ERC warning (wire_dangling) with 0 errors must fail without printing PASS:
            warn_sch = build_base("-12V", dangling_wire=True)
            with self.assertRaises(RuntimeError):
                sb_mod.verify_schematic(warn_sch, net_path)
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with (
                contextlib.redirect_stdout(out_buf),
                contextlib.redirect_stderr(err_buf),
            ):
                rc_warn = isi._verify_schematic(warn_sch, net_path, KICAD_CLI)
            self.assertEqual(rc_warn, 1)
            self.assertNotIn("PASS:", out_buf.getvalue())
            self.assertIn("FAIL:", err_buf.getvalue())

    @unittest.skipUnless(HAS_KICAD_SYMBOLS, "requires KiCad 10 symbol libraries")
    def test_inspect_cli_net_and_symbols_from_net(self) -> None:
        net_text = """(export
  (version "D")
  (components
    (comp (ref "Q1") (value "BC848B") (footprint "Package_TO_SOT_SMD:SOT-23")
      (libsource (lib "Transistor_BJT") (part "BC848")))
  )
  (nets
    (net (code "1") (name "-12V")
      (node (ref "Q1") (pin "2")))
  )
)"""
        with tempfile.TemporaryDirectory() as td:
            net_path = pathlib.Path(td) / "cli.net"
            net_path.write_text(net_text, encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCH_SCRIPT_DIR / "inspect_schematic_inputs.py"),
                    "--net",
                    str(net_path),
                    "--symbols-from-net",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("=== COMPONENTS (1) ===", proc.stdout)
        self.assertIn("-12V", proc.stdout)
        self.assertIn("Transistor_BJT:BC848 extends=['Q_NPN_BEC']", proc.stdout)
