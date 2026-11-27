from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "packs/hardware/extract-pdf-schematic/scripts"
SCRIPT_PATH = SCRIPT_DIR / "extract_schematic.py"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import extract_schematic as es

HAS_MACOS_TOOLS = (
    sys.platform == "darwin"
    and shutil.which("swift") is not None
    and shutil.which("osascript") is not None
)


def build_synthetic_pdf(
    content_stream: bytes,
    mediabox: tuple[int, int, int, int] = (0, 0, 612, 792),
    rotate: int = 0,
    compress: bool = True,
    extra_objs: list[bytes] | None = None,
) -> bytes:
    """Build a minimal valid single-page PDF document for unit and e2e tests."""
    objs: list[bytes] = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    rot_str = f" /Rotate {rotate}".encode() if rotate else b""
    mb = f"[{mediabox[0]} {mediabox[1]} {mediabox[2]} {mediabox[3]}]".encode()
    res_extra = b" /XObject << /Im1 5 0 R >>" if extra_objs else b""
    objs.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox "
        + mb
        + rot_str
        + b" /Contents 4 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >>"
        + res_extra
        + b" >> >>"
    )
    if compress:
        comp = zlib.compress(content_stream)
        objs.append(
            b"<< /Length "
            + str(len(comp)).encode()
            + b" /Filter /FlateDecode >>\nstream\n"
            + comp
            + b"\nendstream"
        )
    else:
        objs.append(
            b"<< /Length "
            + str(len(content_stream)).encode()
            + b" >>\nstream\n"
            + content_stream
            + b"\nendstream"
        )
    if extra_objs:
        objs.extend(extra_objs)

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def read_png_size(png_path: pathlib.Path) -> tuple[int, int]:
    """Read pixel width and height from a PNG IHDR chunk."""
    data = png_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"Not a PNG file: {png_path}")
    return struct.unpack(">II", data[16:24])


class ExtractSchematicUnitTests(unittest.TestCase):
    def test_audit_images_handles_nested_dicts_and_whitespace(self) -> None:
        raw_pdf = (
            b"10 0 obj\n"
            b"<< /Type /XObject /Subtype /Image /DecodeParms << /Predictor 12 /Colors 3 >> "
            b"/Width 1200 /Height 900 >>\n"
            b"endobj\n"
            b"11 0 obj\n"
            b"<< /Type /XObject /Subtype\n/Image /Width 80 /Height 40 >>\n"
            b"endobj\n"
            b"12 0 obj\n"
            b"<< /Type /XObject /Subtype /Form /Resources << /XObject << /Subtype /Image /Width 999 /Height 999 >> >> /BBox [0 0 100 100] >>\n"
            b"endobj\n"
        )
        imgs = es.audit_images(raw_pdf)
        self.assertEqual(
            imgs,
            [
                {"obj": 10, "width": 1200, "height": 900},
                {"obj": 11, "width": 80, "height": 40},
            ],
        )

    def test_extract_content_streams_handles_nested_dicts_and_filters(self) -> None:
        plain_body = b"10 20 100 200 re S"
        flate_body = zlib.compress(b"40 100 500 620 re S")
        font_body = zlib.compress(b"\x00\x01\x00\x00fontdata")
        otf_body = zlib.compress(b"OTTOfontdata")
        raw_pdf = (
            b"1 0 obj\n<< /Length 18 >>\nstream\n"
            + plain_body
            + b"\nendstream\nendobj\n"
            + b"2 0 obj\n<< /Filter /FlateDecode /DecodeParms << /Columns 10 >> /Length 20 >>\nstream\n"
            + flate_body
            + b"\nendstream\nendobj\n"
            + b"3 0 obj\n<< /Filter [/ASCII85Decode /FlateDecode] /Length 10 >>\nstream\n"
            + b"~>end\nendstream\nendobj\n"
            + b"4 0 obj\n<< /Subtype /Image /Width 10 /Height 10 /Filter /FlateDecode >>\nstream\n"
            + flate_body
            + b"\nendstream\nendobj\n"
            + b"5 0 obj\n<< /Filter /FlateDecode /Length 16 >>\nstream\n"
            + font_body
            + b"\nendstream\nendobj\n"
            + b"6 0 obj\n<< /Filter /FlateDecode /Length 16 >>\nstream\n"
            + otf_body
            + b"\nendstream\nendobj\n"
        )
        streams = es.extract_content_streams(raw_pdf)
        self.assertEqual(streams, ["10 20 100 200 re S", "40 100 500 620 re S"])

    def test_detect_footer_max_y_text_and_non_im_image_ignores_unit_form(self) -> None:
        stream = (
            "1 0 0 1 50 30 cm /Fm0 Do\n"
            "24 0 0 24 40 20 cm /X1 Do\n"
            "BT /F1 12 Tf 1 0 0 1 250 55 Tm (Page 3) ET\n"
        )
        self.assertEqual(es.detect_footer_max_y([stream]), 69.0)

        only_unit_form = ["1 0 0 1 50 30 cm /Fm0 Do\n"]
        self.assertEqual(es.detect_footer_max_y(only_unit_form), 0.0)

    def test_detect_crop_box_sheet_rect_origin_zero_and_negative_dims(self) -> None:
        # Sheet rect anchored at (0, 0) with no footer
        pdf0 = build_synthetic_pdf(b"0 0 500 620 re S", compress=False)
        res0 = es.detect_crop_box(pdf0, 612, 792)
        self.assertEqual(res0["method"], "sheet-rect")
        self.assertEqual(res0["crop"], [0.0, 0.0, 500.0, 620.0])

        # Negative width/height `re` above footer
        pdf_neg = build_synthetic_pdf(
            b"BT /F1 10 Tf 1 0 0 1 280 40 Tm (Page 1) ET\n540 720 -500 -620 re S",
            compress=False,
        )
        res_neg = es.detect_crop_box(pdf_neg, 612, 792)
        self.assertEqual(res_neg["method"], "sheet-rect")
        self.assertEqual(res_neg["crop"], [40.0, 100.0, 500.0, 620.0])
        self.assertEqual(res_neg["footer_max_y"], 54.0)

        # Non-zero MediaBox origin
        pdf_off = build_synthetic_pdf(
            b"120 200 400 500 re S",
            mediabox=(100, 100, 612, 792),
            compress=False,
        )
        res_off = es.detect_crop_box(pdf_off, 612, 792, origin_x=100.0, origin_y=100.0)
        self.assertEqual(res_off["method"], "sheet-rect")
        self.assertEqual(res_off["crop"], [120.0, 200.0, 400.0, 500.0])

    def test_detect_crop_box_vector_bounds_includes_re_and_vy_curves(self) -> None:
        stream = (
            b"BT /F1 10 Tf 1 0 0 1 280 30 Tm (Footer) ET\n"
            b"100 150 200 100 re S\n"
            b"200 250 m 350 300 400 450 v S\n"
        )
        pdf = build_synthetic_pdf(stream, compress=False)
        res = es.detect_crop_box(pdf, 612, 792, margin=10.0)
        self.assertEqual(res["method"], "vector-bounds")
        self.assertEqual(res["crop"], [90.0, 140.0, 320.0, 320.0])

        empty_pdf = build_synthetic_pdf(b"", compress=False)
        res_empty = es.detect_crop_box(
            empty_pdf, 612, 792, origin_x=10.0, origin_y=20.0
        )
        self.assertEqual(res_empty["method"], "full-page")
        self.assertEqual(res_empty["crop"], [10.0, 20.0, 612.0, 792.0])

    def test_parse_crop_arg_validation(self) -> None:
        self.assertEqual(
            es.parse_crop_arg("10, 20.5, 300, 400"), [10.0, 20.5, 300.0, 400.0]
        )
        for bad in ("10,20,30", "10,20,0,40", "10,20,30,-5"):
            with self.assertRaises(argparse.ArgumentTypeError):
                es.parse_crop_arg(bad)


@unittest.skipUnless(HAS_MACOS_TOOLS, "requires macOS swift and osascript")
class ExtractSchematicMacOSE2ETests(unittest.TestCase):
    def test_e2e_inspect_extract_render_roundtrip(self) -> None:
        stream = (
            b"q\n"
            b"BT /F1 10 Tf 1 0 0 1 280 40 Tm (Page 12) Tj ET\n"
            b"40 100 500 620 re S\n"
            b"50 110 m 530 710 l S\n"
            b"Q\n"
        )
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            src = tmp / "manual.pdf"
            src.write_bytes(build_synthetic_pdf(stream))
            src_png = tmp / "src.png"
            out_pdf = tmp / "out.pdf"
            out_png = tmp / "out.png"
            ren_png = tmp / "rendered.png"

            r_ins = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "inspect",
                    str(src),
                    "--page",
                    "1",
                    "--preview",
                    str(src_png),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            ins = json.loads(r_ins.stdout)
            self.assertEqual(ins["detected_crop"]["method"], "sheet-rect")
            self.assertEqual(ins["detected_crop"]["crop"], [40.0, 100.0, 500.0, 620.0])
            self.assertEqual(read_png_size(src_png), (1224, 1584))

            r_ext = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "extract",
                    str(src),
                    "--page",
                    "1",
                    "--output",
                    str(out_pdf),
                    "--rotate",
                    "90",
                    "--preview",
                    str(out_png),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            ext = json.loads(r_ext.stdout)
            self.assertEqual(ext["verified"]["page_count"], 1)
            self.assertEqual(ext["verified"]["rotation"], 0)
            self.assertEqual(ext["verified"]["mediabox"], [0, 0, 620, 500])
            self.assertEqual(ext["verified"]["large_images"], [])
            self.assertEqual(read_png_size(out_png), (1240, 1000))

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "render",
                    str(out_pdf),
                    "--output",
                    str(ren_png),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(read_png_size(ren_png), (1240, 1000))

    def test_e2e_rotated_source_pdf_preview_and_extract(self) -> None:
        stream = b"40 100 500 620 re S\n"
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            src = tmp / "rotated90.pdf"
            src.write_bytes(
                build_synthetic_pdf(stream, mediabox=(0, 0, 612, 792), rotate=90)
            )
            src_png = tmp / "rot_src.png"
            out_pdf = tmp / "rot_out.pdf"
            out_png = tmp / "rot_out.png"

            r_ins = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "inspect",
                    str(src),
                    "--page",
                    "1",
                    "--preview",
                    str(src_png),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            ins = json.loads(r_ins.stdout)
            self.assertEqual(ins["rotation"], 90)
            self.assertEqual(ins["neighbors"][0]["rotation"], 90)
            self.assertIsInstance(ins["neighbors"][0]["rotation"], int)
            # Source 612x792 with /Rotate 90 renders as landscape 1584x1224 at 2x
            self.assertEqual(read_png_size(src_png), (1584, 1224))

            r_ext = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "extract",
                    str(src),
                    "--page",
                    "1",
                    "--output",
                    str(out_pdf),
                    "--rotate",
                    "0",
                    "--preview",
                    str(out_png),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            ext = json.loads(r_ext.stdout)
            # /Rotate 90 + --rotate 0 preserves visual landscape orientation (620x500)
            self.assertEqual(ext["verified"]["mediabox"], [0, 0, 620, 500])
            self.assertEqual(ext["verified"]["rotation"], 0)
            self.assertEqual(read_png_size(out_png), (1240, 1000))

    def test_e2e_render_creates_missing_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            src = tmp / "doc.pdf"
            src.write_bytes(build_synthetic_pdf(b"40 100 500 620 re S"))
            nested_png = tmp / "nested" / "dir" / "out.png"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "render",
                    str(src),
                    "--output",
                    str(nested_png),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertTrue(nested_png.is_file())
            self.assertEqual(read_png_size(nested_png), (1224, 1584))

    def test_e2e_extract_in_place_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            doc = tmp / "inplace.pdf"
            doc.write_bytes(build_synthetic_pdf(b"40 100 500 620 re S"))
            r_ext = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "extract",
                    str(doc),
                    "--page",
                    "1",
                    "--output",
                    str(doc),
                    "--rotate",
                    "90",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            ext = json.loads(r_ext.stdout)
            self.assertEqual(ext["verified"]["page_count"], 1)
            self.assertEqual(ext["verified"]["mediabox"], [0, 0, 620, 500])
