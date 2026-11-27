"""Unit and macOS end-to-end tests for packs/hardware/describe-schematic-pdf."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "packs" / "hardware" / "describe-schematic-pdf" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import render_schematic_tiles
import verify_circuit_md


def _make_sample_md(
    *,
    extra_bom: str = "",
    extra_nets: str = "",
    drop_vt1_c: bool = False,
    dup_pin: bool = False,
    short_r1: bool = False,
    orphan_net: bool = False,
    dup_net: bool = False,
    nc_pins: str = "`TP2.1`",
    extra_tp2_bom: bool = True,
) -> str:
    vt1_c_entry = "" if drop_vt1_c else "`VT1.C`, "
    r1_pins = "`R1.1`, `R1.2`, `XS1.T`" if short_r1 else "`R1.1`, `XS1.T`"
    out_sig_line = (
        "| `OUT_SIG` | `DA1.3`, `TP1.1` | Op-amp input |\n"
        if short_r1
        else "| `OUT_SIG` | `R1.2`, `DA1.3` | Divider to op-amp |\n"
    )
    tp1_in_gnd = "" if (orphan_net or short_r1) else "`TP1.1`, "
    dup_token = "`R1.1`, " if dup_pin else ""
    orphan_line = "| `ORPHAN` | `TP1.1` | Single-pin orphan |\n" if orphan_net else ""
    dup_net_line = (
        "| `SW_NODE` | `Q1.D`, `VT1.E` | Duplicate net |\n" if dup_net else ""
    )
    tp2_bom_line = (
        "| `TP2` | `TP2` | Test Point | Test | Spare pad |\n" if extra_tp2_bom else ""
    )
    nc_line = f"| `NC` | {nc_pins} | Unconnected |\n" if nc_pins else ""

    return f"""# Sample Module — Circuit Description

## Metadata

| Field | Value |
| --- | --- |
| **Module Title** | SAMPLE |

---

## Bill of Materials (BOM)

| Ref | Value / Part | Category / Spec | Block | Notes |
| --- | --- | --- | --- | --- |
| `C1` | `47uF` | Capacitor, Electrolytic | Power | Bulk cap |
| `C2` | `0.1uF` | Capacitor, Ceramic | Power | Decoupling |
| `DA1` | `TL072` | IC, Dual Op-Amp | Core | Buffer |
| `Q1` | `2N7000` | Transistor, MOSFET | Switch | FET switch |
| `R1` | `10k` | Resistor | Input | Series resistor |
| `R2` | `B100k` | Potentiometer, Linear | Level | Level pot |
| `SW1` | `ON-ON` | Switch, SPDT | Mode | Mode switch |
| `TP1` | `TP1` | Test Point | Test | Ground pad |
{tp2_bom_line}| `VD1` | `1N4148` | Diode, Switching | Clamp | Signal diode |
| `VT1` | `BC548` | Transistor, NPN | Buffer | Emitter follower |
| `XP1` | `2x5 Header` | Connector, 2x5 | Power | Power |
| `XS1` | `IN` | Jack, 3.5mm Mono Switched | I/O | Input |
{extra_bom}

---

## Pin-to-Pin Netlist

| Net | Connected Pins | Description |
| --- | --- | --- |
| `+12V` | `XP1.9`, `XP1.10`, `C1.+`, `C2.1`, `DA1.8`, `VT1.B` | Positive rail |
| `-12V` | `XP1.1`, `XP1.2`, `C1.-`, `DA1.4` | Negative rail |
| `GND` | {tp1_in_gnd}{vt1_c_entry}`XP1.3`, `XP1.4`, `XP1.5`, `XP1.6`, `XP1.7`, `XP1.8`, `C2.2`, `XS1.S`, `XS1.SW`, `R2.CCW`, `Q1.S`, `SW1.3` | Ground |
| `IN_SIG` | {r1_pins} | Input signal |
{out_sig_line}| `POT_NODE` | {dup_token}`R2.CW`, `R2.W`, `VD1.A`, `Q1.G` | Pot and diode |
| `SW_NODE` | `VD1.K`, `SW1.1`, `SW1.2`, `Q1.D`, `VT1.E` | Switch node |
| `OP_NODE` | `DA1.1`, `DA1.2`, `DA1.5`, `DA1.6`, `DA1.7` | Op-amp nodes |
{orphan_line}{dup_net_line}{extra_nets}{nc_line}"""


def _run_verify(md_text: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        md_path = Path(tmp) / "spec.md"
        md_path.write_text(md_text, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = verify_circuit_md.verify_file(md_path)
        return rc, buf.getvalue()


class VerifyCircuitMdTests(unittest.TestCase):
    def test_valid_single_board_spec(self) -> None:
        rc, out = _run_verify(_make_sample_md())
        self.assertEqual(rc, 0, out)
        self.assertIn("Errors=0", out)

    def test_valid_dual_board_spec(self) -> None:
        extra_bom = (
            "| `DA3` | `NJM4556AD` | IC, Dual Power Op-Amp | Phones | Driver |\n"
            "| `XP2` | `1x16 Header` | Connector, Board-to-Board | Interconnect | Header |\n"
            "| `XS5` | `PHONES` | Jack, 3.5mm TRS Stereo | I/O | Stereo jack |\n"
            "| `XS11` | `1x16 Socket` | Connector, Board-to-Board | Interconnect | Socket |\n"
        )
        xp2_pins = ", ".join(f"`XP2.{i}`" for i in range(1, 17))
        xs11_pins = ", ".join(f"`XS11.{i}`" for i in range(1, 17))
        da3_pins = ", ".join(f"`DA3.{i}`" for i in range(1, 9))
        extra_nets = (
            f"| `INTERCONNECT` | {xp2_pins}, {xs11_pins} | Interconnect |\n"
            f"| `PHONES` | {da3_pins}, `XS5.T`, `XS5.R`, `XS5.S` | Phones |\n"
        )
        rc, out = _run_verify(
            _make_sample_md(extra_bom=extra_bom, extra_nets=extra_nets)
        )
        self.assertEqual(rc, 0, out)

    def test_detects_missing_and_extra_refs(self) -> None:
        rc_missing, out_missing = _run_verify(
            _make_sample_md(extra_bom="| `R99` | `1k` | Resistor | Extra | Unused |\n")
        )
        self.assertEqual(rc_missing, 2, out_missing)
        self.assertIn("BOM refs missing from netlist: ['R99']", out_missing)

        rc_extra, out_extra = _run_verify(
            _make_sample_md(
                extra_nets="| `EXTRA` | `TP3.1`, `TP2.1` | Extra |\n", nc_pins=""
            )
        )
        self.assertEqual(rc_extra, 1, out_extra)
        self.assertIn("Netlist refs missing from BOM: ['TP3']", out_extra)

    def test_detects_duplicate_pin_across_nets(self) -> None:
        rc, out = _run_verify(_make_sample_md(dup_pin=True))
        self.assertEqual(rc, 1, out)
        self.assertIn("Duplicate pin 'R1.1' on nets 'IN_SIG' and 'POT_NODE'", out)

    def test_detects_shorted_passive(self) -> None:
        rc, out = _run_verify(_make_sample_md(short_r1=True))
        self.assertEqual(rc, 1, out)
        self.assertIn("Shorted 2-pin component R1 on net 'IN_SIG'", out)

    def test_detects_orphan_net(self) -> None:
        rc, out = _run_verify(_make_sample_md(orphan_net=True))
        self.assertEqual(rc, 1, out)
        self.assertIn("Orphan net 'ORPHAN' has <2 pins: ['TP1.1']", out)

    def test_detects_pin_mismatch(self) -> None:
        rc, out = _run_verify(_make_sample_md(drop_vt1_c=True))
        self.assertEqual(rc, 1, out)
        self.assertIn("Pin mismatch on VT1 (BC548): expected ['B', 'C', 'E']", out)

    def test_detects_duplicate_net_name(self) -> None:
        rc, out = _run_verify(_make_sample_md(dup_net=True))
        self.assertGreater(rc, 0, out)
        self.assertIn("Duplicate net 'SW_NODE'", out)

    def test_flexible_table_formatting_and_inference_edge_cases(self) -> None:
        # Non-polarized electrolytic, RV* pot, empty trailing BOM cell,
        # jack with 6x10mm physical dimensions, notes mentioning DPDT / 10-pin,
        # DNP resistor on NC, aligned Netlist header, and BOM immediately before ---.
        extra_bom = (
            "| `C3` | `10uF` | Capacitor, Non-polarized Electrolytic | Coupling ||\n"
            "| `RV1` | `100k` | Potentiometer | Gain | Control |\n"
            "| `SW2` | `SPST` | Switch, SPST | Bypass | Replaced DPDT from rev 1 |\n"
            "| `U1` | `CUSTOM_IC` | IC, 6-pin Optocoupler | VCA | Connects to 10-pin header |\n"
            "| `XS2` | `6x10mm Jack` | Jack, 3.5mm Mono | Out | Body 6x10mm |\n"
            "| `R3` | `DNP` | Resistor | Spare | Unpopulated |\n"
        )
        u1_pins = ", ".join(f"`U1.{i}`" for i in range(1, 7))
        extra_nets = (
            f"| `EDGE_A` | `C3.1`, `RV1.CCW`, `RV1.W`, `SW2.1`, {u1_pins} | Edge A |\n"
            "| `EDGE_B` | `C3.2`, `RV1.CW`, `SW2.2`, `XS2.T`, `XS2.S`, `XS2.SW` | Edge B |\n"
        )
        text = _make_sample_md(
            extra_bom=extra_bom,
            extra_nets=extra_nets,
            nc_pins="`TP2.1`, `R3.1`, `R3.2`",
        )
        # Remove blank line before --- after BOM, and pad Netlist header columns
        text = text.replace(
            "\n\n---\n\n## Pin-to-Pin Netlist", "\n---\n\n## Pin-to-Pin Netlist"
        )
        text = text.replace(
            "| Net | Connected Pins | Description |",
            "| Net   | Connected Pins       | Description |",
        )
        rc, out = _run_verify(text)
        self.assertEqual(rc, 0, out)

    def test_verify_readme_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "schematics").mkdir()
            (root / "schematics" / "My Schematic.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "schematics" / "test.md").write_text("# test\n", encoding="utf-8")
            readme = root / "README.md"
            readme.write_text(
                "Prose mention (see missing.md) should be ignored.\n"
                "[Ext](https://example.com/a.pdf) "
                "[PDF](schematics/My%20Schematic.pdf) "
                "[MD](schematics/test.md#metadata)\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_ok = verify_circuit_md.verify_readme(readme)
            self.assertEqual(rc_ok, 0, buf.getvalue())

            readme.write_text("[Broken](schematics/missing.md)\n", encoding="utf-8")
            buf_bad = io.StringIO()
            with contextlib.redirect_stdout(buf_bad):
                rc_bad = verify_circuit_md.verify_readme(readme)
            self.assertEqual(rc_bad, 1, buf_bad.getvalue())

    def test_cli_exit_codes_and_readme_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "circuit.md"
            spec.write_text(_make_sample_md(), encoding="utf-8")
            readme = root / "README.md"
            readme.write_text("[Circuit](circuit.md)\n", encoding="utf-8")

            res_ok = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "verify_circuit_md.py"),
                    str(spec),
                    "--readme",
                    str(readme),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_ok.returncode, 0, res_ok.stdout + res_ok.stderr)

            spec.write_text(_make_sample_md(short_r1=True), encoding="utf-8")
            res_fail = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "verify_circuit_md.py"),
                    str(spec),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_fail.returncode, 1, res_fail.stdout + res_fail.stderr)

    def test_report_designator_gaps(self) -> None:
        gaps = verify_circuit_md.report_designator_gaps({"R1", "R3", "C1", "C2"})
        self.assertEqual(gaps, ["R: skipped [2]"])


class RenderSchematicTilesTests(unittest.TestCase):
    def test_rejects_invalid_cli_arguments(self) -> None:
        bad_invocations = [
            ["crop", __file__, "--rect", "1,2,3", "--output", "/tmp/out.png"],
            ["crop", __file__, "--rect", "0,0,nan,10", "--output", "/tmp/out.png"],
            [
                "crop",
                __file__,
                "--rect",
                "0,0,10,10",
                "--scale",
                "0",
                "--output",
                "/tmp/out.png",
            ],
            ["tile", "/nonexistent/missing.pdf", "--out-dir", "/tmp/out_tiles"],
            ["tile", __file__, "--out-dir", "/tmp/out_tiles", "--cols", "0"],
            ["tile", __file__, "--out-dir", "/tmp/out_tiles", "--scale", "nan"],
            ["tile", __file__, "--out-dir", "/tmp/out_tiles", "--stem", "a/b"],
            ["search-manual", __file__, "R1", "--max-per-term", "0"],
        ]
        for argv in bad_invocations:
            res = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "render_schematic_tiles.py"), *argv],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(res.returncode, 0, f"Expected failure for {argv}")

    @unittest.skipUnless(
        sys.platform == "darwin" and shutil.which("swift"),
        "macOS Swift required",
    )
    def test_macos_tile_crop_and_search_manual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "sample_schematic.pdf"

            swift_make_pdf = r"""
import Foundation
import CoreGraphics
import AppKit

let inputData = FileHandle.standardInput.readDataToEndOfFile()
let payload = try JSONSerialization.jsonObject(with: inputData) as! [String: Any]
let outPath = payload["out"] as! String

var box = CGRect(x: 0, y: 0, width: 400, height: 300)
guard let consumer = CGDataConsumer(url: URL(fileURLWithPath: outPath) as CFURL),
      let ctx = CGContext(consumer: consumer, mediaBox: &box, nil) else {
    exit(1)
}
ctx.beginPDFPage(nil)
ctx.setStrokeColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
ctx.stroke(CGRect(x: 20, y: 20, width: 360, height: 260))
let nsCtx = NSGraphicsContext(cgContext: ctx, flipped: false)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = nsCtx
("R61 2M trimmer -12V" as NSString).draw(
    at: NSPoint(x: 40, y: 140),
    withAttributes: [.font: NSFont.systemFont(ofSize: 14)]
)
NSGraphicsContext.restoreGraphicsState()
ctx.endPDFPage()
ctx.closePDF()
"""
            render_schematic_tiles.run_swift(swift_make_pdf, {"out": str(pdf_path)})
            self.assertTrue(pdf_path.is_file())

            tiles_dir = tmp_path / "tiles"
            res_tile = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "render_schematic_tiles.py"),
                    "tile",
                    str(pdf_path),
                    "--out-dir",
                    str(tiles_dir),
                    "--cols",
                    "2",
                    "--rows",
                    "1",
                    "--scale",
                    "2.0",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_tile.returncode, 0, res_tile.stderr)
            info = json.loads(res_tile.stdout)
            self.assertEqual(info["page_count"], 1)
            self.assertEqual(info["rotation"], 0)
            self.assertEqual(info["page_size"], [400.0, 300.0])
            self.assertEqual(len(info["tiles"]), 2)
            for t in info["tiles"]:
                p = Path(t["path"])
                self.assertTrue(p.is_file())
                self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreater(t["width_px"], 0)
                self.assertGreater(t["height_px"], 0)

            crop_png = tmp_path / "zoom.png"
            res_crop = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "render_schematic_tiles.py"),
                    "crop",
                    str(pdf_path),
                    "--rect",
                    "20,100,180,80",
                    "--output",
                    str(crop_png),
                    "--scale",
                    "4.0",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_crop.returncode, 0, res_crop.stderr)
            crop_info = json.loads(res_crop.stdout)
            self.assertEqual(crop_info["width_px"], 720)
            self.assertEqual(crop_info["height_px"], 320)
            self.assertEqual(crop_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

            res_search = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "render_schematic_tiles.py"),
                    "search-manual",
                    str(pdf_path),
                    "--",
                    "R61",
                    "-12V",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_search.returncode, 0, res_search.stderr)
            self.assertIn("p.1 [R61]:", res_search.stdout)
            self.assertIn("p.1 [-12V]:", res_search.stdout)
            self.assertIn("R61 2M trimmer -12V", res_search.stdout)

    @unittest.skipUnless(
        sys.platform == "darwin" and shutil.which("swift"),
        "macOS Swift required",
    )
    def test_macos_rotated_and_offset_mediabox_tiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rot_offset.pdf"

            # Create a 200x400 PDF with non-zero origin (50, 100) and rotation=90,
            # filled completely with red so every rendered tile must contain red pixels.
            swift_make_rot = r"""
import Foundation
import CoreGraphics
import PDFKit

let inputData = FileHandle.standardInput.readDataToEndOfFile()
let payload = try JSONSerialization.jsonObject(with: inputData) as! [String: Any]
let outPath = payload["out"] as! String

var box = CGRect(x: 50, y: 100, width: 200, height: 400)
guard let consumer = CGDataConsumer(url: URL(fileURLWithPath: outPath) as CFURL),
      let ctx = CGContext(consumer: consumer, mediaBox: &box, nil) else {
    exit(1)
}
ctx.beginPDFPage(nil)
ctx.setFillColor(CGColor(red: 1, green: 0, blue: 0, alpha: 1))
ctx.fill(box)
ctx.endPDFPage()
ctx.closePDF()

let doc = PDFDocument(url: URL(fileURLWithPath: outPath))!
doc.page(at: 0)!.rotation = 90
doc.write(toFile: outPath)
"""
            render_schematic_tiles.run_swift(swift_make_rot, {"out": str(pdf_path)})

            tiles_dir = tmp_path / "rot_tiles"
            res_tile = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS_DIR / "render_schematic_tiles.py"),
                    "tile",
                    str(pdf_path),
                    "--out-dir",
                    str(tiles_dir),
                    "--cols",
                    "2",
                    "--rows",
                    "1",
                    "--scale",
                    "1.0",
                    "--overlap",
                    "0",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(res_tile.returncode, 0, res_tile.stderr)
            info = json.loads(res_tile.stdout)
            self.assertEqual(info["rotation"], 90)
            self.assertEqual(info["page_size"], [400.0, 200.0])
            self.assertEqual(len(info["tiles"]), 2)

            # Verify both tiles (left 200x200 and right 200x200 of upright 400x200 sheet)
            # actually have red pixels at their center.
            swift_check_center = r"""
import Foundation
import AppKit

let inputData = FileHandle.standardInput.readDataToEndOfFile()
let payload = try JSONSerialization.jsonObject(with: inputData) as! [String: Any]
let paths = payload["paths"] as! [String]
for p in paths {
    let img = NSImage(contentsOfFile: p)!
    let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
    let c = rep.colorAt(x: rep.pixelsWide / 2, y: rep.pixelsHigh / 2)!
    let isRed = c.redComponent > 0.9 && c.greenComponent < 0.3 && c.blueComponent < 0.3
    print("\(rep.pixelsWide)x\(rep.pixelsHigh):\(isRed ? "red" : "other")")
}
"""
            chk = render_schematic_tiles.run_swift(
                swift_check_center,
                {"paths": [t["path"] for t in info["tiles"]]},
            )
            self.assertEqual(chk.strip().splitlines(), ["200x200:red", "200x200:red"])


if __name__ == "__main__":
    os.chdir(ROOT)
    unittest.main()
