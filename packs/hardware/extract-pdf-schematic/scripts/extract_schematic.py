#!/usr/bin/env python3
"""Extract, crop, rotate, and verify vector schematics from PDF pages on macOS."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

_JXA_RENDER_PAGE_FN = """
function renderPageToPng(page, bounds, outPath, scale) {
  var rot = ((Number(page.rotation) % 360) + 360) % 360;
  var pw = (rot === 90 || rot === 270) ? bounds.size.height : bounds.size.width;
  var ph = (rot === 90 || rot === 270) ? bounds.size.width : bounds.size.height;
  var w = Math.max(1, Math.round(pw * scale));
  var h = Math.max(1, Math.round(ph * scale));
  var rep = $.NSBitmapImageRep.alloc.initWithBitmapDataPlanesPixelsWidePixelsHighBitsPerSampleSamplesPerPixelHasAlphaIsPlanarColorSpaceNameBytesPerRowBitsPerPixel(
    null, w, h, 8, 4, true, false, $.NSCalibratedRGBColorSpace, 0, 0
  );
  if (!rep) {
    throw new Error("Failed to allocate bitmap image rep");
  }
  $.NSGraphicsContext.saveGraphicsState;
  var ctx = $.NSGraphicsContext.graphicsContextWithBitmapImageRep(rep);
  if (!ctx) {
    $.NSGraphicsContext.restoreGraphicsState;
    throw new Error("Failed to create graphics context");
  }
  $.NSGraphicsContext.setCurrentContext(ctx);
  var cg = ctx.CGContext;
  $.CGContextSetRGBFillColor(cg, 1, 1, 1, 1);
  $.CGContextFillRect(cg, $.CGRectMake(0, 0, w, h));
  $.CGContextScaleCTM(cg, scale, scale);
  page.drawWithBoxToContext($.kPDFDisplayBoxMediaBox, cg);
  $.NSGraphicsContext.restoreGraphicsState;
  var pngData = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $({}));
  if (!pngData || !pngData.writeToFileAtomically(outPath, true)) {
    throw new Error("Failed to write PNG: " + outPath);
  }
  return { path: outPath, width_px: w, height_px: h };
}
"""


def run_jxa(script: str) -> str:
    """Execute a JXA script via osascript and return stdout, ignoring XPC noise on stderr."""
    res = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"osascript failed ({res.returncode}): {res.stderr.strip()}")
    return res.stdout


def _parse_jxa_json(output: str) -> dict:
    """Parse JSON from the last non-empty line of JXA stdout."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("osascript produced no JSON output")
    return json.loads(lines[-1])


def get_pdf_info_and_single_page(
    pdf_path: Path,
    page_num: int,
    single_pdf_out: Path,
    preview_out: Path | None = None,
    scale: float = 2.0,
) -> dict:
    """Inspect PDF page metadata, export single-page PDF, and optionally render PNG preview."""
    single_pdf_out.parent.mkdir(parents=True, exist_ok=True)
    if preview_out is not None:
        preview_out.parent.mkdir(parents=True, exist_ok=True)

    p_in = json.dumps(str(pdf_path.resolve()))
    p_single = json.dumps(str(single_pdf_out.resolve()))
    p_prev = json.dumps(str(preview_out.resolve())) if preview_out else "null"

    jxa = f"""
ObjC.import("PDFKit");
ObjC.import("AppKit");
ObjC.import("CoreGraphics");
ObjC.import("Foundation");
{_JXA_RENDER_PAGE_FN}
var url = $.NSURL.fileURLWithPath({p_in});
var doc = $.PDFDocument.alloc.initWithURL(url);
if (!doc) {{
  throw new Error("Could not open PDF: " + {p_in});
}}
var count = Number(doc.pageCount);
var pageNum = {page_num};
if (pageNum < 1 || pageNum > count) {{
  throw new Error("Page " + pageNum + " out of range (1.." + count + ")");
}}
var idx = pageNum - 1;

var neighbors = [];
for (var offset = -1; offset <= 1; offset++) {{
  var ni = idx + offset;
  if (ni >= 0 && ni < count) {{
    var np = doc.pageAtIndex(ni);
    var nb = np.boundsForBox($.kPDFDisplayBoxMediaBox);
    var nlbl = ObjC.unwrap(np.label) || null;
    var nstr = String(ObjC.unwrap(np.string) || "").replace(/\\s+/g, " ").trim().substring(0, 140);
    neighbors.push({{
      page: ni + 1,
      label: nlbl,
      width: nb.size.width,
      height: nb.size.height,
      rotation: Number(np.rotation),
      snippet: nstr
    }});
  }}
}}

var page = doc.pageAtIndex(idx);
var bounds = page.boundsForBox($.kPDFDisplayBoxMediaBox);
var single = $.PDFDocument.alloc.init;
single.insertPageAtIndex(page, 0);
if (!single.writeToFile({p_single})) {{
  throw new Error("Failed to write single-page PDF: " + {p_single});
}}

var prevOut = {p_prev};
var previewInfo = null;
if (prevOut !== null) {{
  previewInfo = renderPageToPng(page, bounds, prevOut, {scale});
}}

JSON.stringify({{
  page_count: count,
  page: pageNum,
  label: ObjC.unwrap(page.label) || null,
  mediabox: [bounds.origin.x, bounds.origin.y, bounds.size.width, bounds.size.height],
  rotation: Number(page.rotation),
  neighbors: neighbors,
  preview: previewInfo
}});
"""
    return _parse_jxa_json(run_jxa(jxa))


def render_page_png(
    pdf_path: Path, page_num: int, png_out: Path, scale: float = 2.0
) -> dict:
    """Render a PDF page to PNG at the given scale factor."""
    png_out.parent.mkdir(parents=True, exist_ok=True)
    p_in = json.dumps(str(pdf_path.resolve()))
    p_out = json.dumps(str(png_out.resolve()))
    jxa = f"""
ObjC.import("PDFKit");
ObjC.import("AppKit");
ObjC.import("CoreGraphics");
ObjC.import("Foundation");
{_JXA_RENDER_PAGE_FN}
var url = $.NSURL.fileURLWithPath({p_in});
var doc = $.PDFDocument.alloc.initWithURL(url);
if (!doc) {{
  throw new Error("Could not open PDF: " + {p_in});
}}
var count = Number(doc.pageCount);
var pageNum = {page_num};
if (pageNum < 1 || pageNum > count) {{
  throw new Error("Page " + pageNum + " out of range (1.." + count + ")");
}}
var page = doc.pageAtIndex(pageNum - 1);
var bounds = page.boundsForBox($.kPDFDisplayBoxMediaBox);
JSON.stringify(renderPageToPng(page, bounds, {p_out}, {scale}));
"""
    return _parse_jxa_json(run_jxa(jxa))


def verify_pdf_metadata(pdf_path: Path) -> dict:
    """Return page count, MediaBox, rotation, file size, and /Subtype /Image audit."""
    p_in = json.dumps(str(pdf_path.resolve()))
    jxa = f"""
ObjC.import("PDFKit");
ObjC.import("Foundation");

var url = $.NSURL.fileURLWithPath({p_in});
var doc = $.PDFDocument.alloc.initWithURL(url);
if (!doc) {{
  throw new Error("Could not open PDF: " + {p_in});
}}
var count = Number(doc.pageCount);
if (count < 1) {{
  JSON.stringify({{
    page_count: 0,
    mediabox: null,
    rotation: null
  }});
}} else {{
  var page = doc.pageAtIndex(0);
  var bounds = page.boundsForBox($.kPDFDisplayBoxMediaBox);
  JSON.stringify({{
    page_count: count,
    mediabox: [bounds.origin.x, bounds.origin.y, bounds.size.width, bounds.size.height],
    rotation: Number(page.rotation)
  }});
}}
"""
    info = _parse_jxa_json(run_jxa(jxa))
    raw = pdf_path.read_bytes()
    info["size_bytes"] = len(raw)
    info["images"] = audit_images(raw)
    info["large_images"] = [
        img for img in info["images"] if max(img["width"], img["height"]) >= 500
    ]
    return info


def _find_matching_dict_end(data: bytes, start_idx: int) -> int | None:
    """Find the byte index just after the matching `>>` for a PDF dictionary at `start_idx`."""
    n = len(data)
    if data[start_idx : start_idx + 2] != b"<<":
        return None
    depth = 1
    i = start_idx + 2
    paren_depth = 0
    while i < n:
        ch = data[i : i + 1]
        if paren_depth > 0:
            if ch == b"\\":
                i += 2
                continue
            if ch == b"(":
                paren_depth += 1
            elif ch == b")":
                paren_depth -= 1
            i += 1
            continue
        if ch == b"(":
            paren_depth = 1
            i += 1
        elif data[i : i + 2] == b"<<":
            depth += 1
            i += 2
        elif data[i : i + 2] == b">>":
            depth -= 1
            i += 2
            if depth == 0:
                return i
        else:
            i += 1
    return None


def _iter_pdf_objects(pdf_bytes: bytes):
    """Yield `(obj_num, dict_bytes, dict_end_pos)` for indirect PDF dictionary objects."""
    for m in re.finditer(rb"(\d+)\s+\d+\s+obj\b\s*<<", pdf_bytes):
        obj_num = int(m.group(1))
        dict_start = m.end() - 2
        dict_end = _find_matching_dict_end(pdf_bytes, dict_start)
        if dict_end is None:
            continue
        yield obj_num, pdf_bytes[dict_start + 2 : dict_end - 2], dict_end


def _strip_nested_dicts(dict_bytes: bytes) -> bytes:
    """Replace nested `<< ... >>` sub-dictionaries with spaces so top-level keys match cleanly."""
    out = bytearray()
    n = len(dict_bytes)
    i = 0
    depth = 0
    paren_depth = 0
    while i < n:
        ch = dict_bytes[i : i + 1]
        if paren_depth > 0:
            if ch == b"\\":
                if depth == 0:
                    out.extend(dict_bytes[i : i + 2])
                i += 2
                continue
            if ch == b"(":
                paren_depth += 1
            elif ch == b")":
                paren_depth -= 1
            if depth == 0:
                out.extend(ch)
            i += 1
            continue
        if ch == b"(":
            paren_depth = 1
            if depth == 0:
                out.extend(ch)
            i += 1
        elif dict_bytes[i : i + 2] == b"<<":
            if depth == 0:
                out.append(0x20)
            depth += 1
            i += 2
        elif dict_bytes[i : i + 2] == b">>" and depth > 0:
            depth -= 1
            if depth == 0:
                out.append(0x20)
            i += 2
        else:
            if depth == 0:
                out.extend(ch)
            i += 1
    return bytes(out)


def audit_images(pdf_bytes: bytes) -> list[dict]:
    """Find /Subtype /Image XObjects and their pixel dimensions."""
    images = []
    for obj_num, dict_bytes, _ in _iter_pdf_objects(pdf_bytes):
        top_hdr = _strip_nested_dicts(dict_bytes)
        if re.search(rb"/Subtype\s*/Image\b", top_hdr):
            w = re.search(rb"/Width\s+(\d+)", top_hdr)
            h = re.search(rb"/Height\s+(\d+)", top_hdr)
            if w and h:
                images.append(
                    {
                        "obj": obj_num,
                        "width": int(w.group(1)),
                        "height": int(h.group(1)),
                    }
                )
    return images


def extract_content_streams(pdf_bytes: bytes) -> list[str]:
    """Decompress PDF page content streams, skipping images, unsupported filters, and fonts."""
    streams = []
    stream_re = re.compile(rb"\s*stream(?:\r\n|\n)(.*?)endstream", re.DOTALL)
    for _, dict_bytes, dict_end in _iter_pdf_objects(pdf_bytes):
        m_stream = stream_re.match(pdf_bytes, dict_end)
        if not m_stream:
            continue
        top_hdr = _strip_nested_dicts(dict_bytes)
        if re.search(rb"/Subtype\s*/Image\b", top_hdr):
            continue
        raw = m_stream.group(1)
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]

        m_filter = re.search(
            rb"/Filter\s*(?:\[\s*([^\]]*)\]|(/[A-Za-z0-9_.-]+))", top_hdr
        )
        if m_filter is None:
            dec = raw
        elif m_filter.group(2) == b"/FlateDecode" or (
            m_filter.group(1) is not None
            and re.fullmatch(rb"\s*/FlateDecode\s*", m_filter.group(1))
        ):
            try:
                dec = zlib.decompress(raw)
            except zlib.error:
                continue
        else:
            continue

        if dec.startswith((b"true\x00", b"\x00\x01\x00\x00", b"OTTO")):
            continue
        streams.append(dec.decode("latin1", errors="ignore"))
    return streams


def detect_footer_max_y(streams: list[str], origin_y: float = 0.0) -> float:
    """Estimate maximum Y of bottom footer logos/page numbers (within bottom 120 pt)."""
    max_y = origin_y
    for text in streams:
        for m in re.finditer(
            r"([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+cm\s+/[A-Za-z0-9_.-]+\s+Do\b",
            text,
        ):
            d, f = float(m.group(4)), float(m.group(6))
            if (
                origin_y < f < origin_y + 120.0
                and 4.0 <= d < 120.0
                and (f + d - origin_y) < 120.0
            ):
                max_y = max(max_y, f + d)
        for bt in re.finditer(r"\bBT\b(.*?)\bET\b", text, re.DOTALL):
            block = bt.group(1)
            for tm in re.finditer(
                r"([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+Tm\b",
                block,
            ):
                a, d, ty = float(tm.group(1)), float(tm.group(4)), float(tm.group(6))
                if origin_y < ty < origin_y + 120.0:
                    est_h = max(abs(a), abs(d), 14.0)
                    max_y = max(max_y, ty + est_h)
    return round(max_y, 3)


def _normalize_rect(
    x: float, y: float, w: float, h: float
) -> tuple[float, float, float, float]:
    """Normalize PDF `re` rectangle dimensions so width and height are non-negative."""
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return x, y, w, h


def detect_crop_box(
    pdf_bytes: bytes,
    page_w: float,
    page_h: float,
    margin: float = 18.0,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> dict:
    """Auto-detect the schematic crop box (x, y, w, h) excluding bottom footers."""
    streams = extract_content_streams(pdf_bytes)
    footer_max_y = detect_footer_max_y(streams, origin_y=origin_y)
    has_footer = footer_max_y > origin_y
    x_min, y_min = origin_x, origin_y
    x_max, y_max = origin_x + page_w, origin_y + page_h

    # Pass 1: Look for an explicit page-coordinate sheet rectangle (e.g., KiCad A3 frame clip)
    sheet_candidates = []
    for text in streams:
        for m in re.finditer(
            r"([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+re\b", text
        ):
            x, y, w, h = _normalize_rect(
                float(m.group(1)),
                float(m.group(2)),
                float(m.group(3)),
                float(m.group(4)),
            )
            is_full_page = abs(w - page_w) <= 2.0 and abs(h - page_h) <= 2.0
            y_ok = y > footer_max_y if has_footer else y >= y_min
            if (
                not is_full_page
                and x >= x_min
                and y_ok
                and w > 0.55 * page_w
                and h > 0.55 * page_h
                and (x + w) <= x_max + 1.0
                and (y + h) <= y_max + 1.0
            ):
                sheet_candidates.append((w * h, x, y, w, h))

    if sheet_candidates:
        sheet_candidates.sort(reverse=True)
        _, x, y, w, h = sheet_candidates[0]
        return {
            "crop": [round(x, 3), round(y, 3), round(w, 3), round(h, 3)],
            "method": "sheet-rect",
            "footer_max_y": footer_max_y,
        }

    # Pass 2: Compute tight bounding box of vector path vertices above footer_max_y
    xs: list[float] = []
    ys: list[float] = []
    y_floor = footer_max_y if has_footer else y_min

    def _record_pt(vx: float, vy: float) -> None:
        y_in_bounds = (vy > y_floor) if has_footer else (vy >= y_floor)
        if x_min <= vx <= x_max and y_in_bounds and vy <= y_max:
            xs.append(vx)
            ys.append(vy)

    for text in streams:
        stripped = re.sub(r"\bBT\b.*?\bET\b", " ", text, flags=re.DOTALL)
        for m in re.finditer(r"([-0-9.]+)\s+([-0-9.]+)\s+(?:m|l)\b", stripped):
            _record_pt(float(m.group(1)), float(m.group(2)))
        for m in re.finditer(
            r"([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+c\b",
            stripped,
        ):
            for idx in (1, 3, 5):
                _record_pt(float(m.group(idx)), float(m.group(idx + 1)))
        for m in re.finditer(
            r"([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+(?:v|y)\b",
            stripped,
        ):
            for idx in (1, 3):
                _record_pt(float(m.group(idx)), float(m.group(idx + 1)))
        for m in re.finditer(
            r"([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+([-0-9.]+)\s+re\b",
            stripped,
        ):
            rx, ry, rw, rh = _normalize_rect(
                float(m.group(1)),
                float(m.group(2)),
                float(m.group(3)),
                float(m.group(4)),
            )
            if abs(rw - page_w) <= 2.0 and abs(rh - page_h) <= 2.0:
                continue
            _record_pt(rx, ry)
            _record_pt(rx + rw, ry + rh)

    if xs and ys:
        y_clamp_min = max(footer_max_y + 2.0, y_min) if has_footer else y_min
        x0 = max(x_min, min(xs) - margin)
        y0 = max(y_clamp_min, min(ys) - margin)
        x1 = min(x_max, max(xs) + margin)
        y1 = min(y_max, max(ys) + margin)
        if x1 > x0 and y1 > y0:
            return {
                "crop": [
                    round(x0, 3),
                    round(y0, 3),
                    round(x1 - x0, 3),
                    round(y1 - y0, 3),
                ],
                "method": "vector-bounds",
                "footer_max_y": footer_max_y,
            }

    return {
        "crop": [
            round(origin_x, 3),
            round(origin_y, 3),
            round(page_w, 3),
            round(page_h, 3),
        ],
        "method": "full-page",
        "footer_max_y": footer_max_y,
    }


def extract_via_coregraphics(
    src_pdf: Path, page_num: int, out_pdf: Path, crop: list[float], rotate_cw: int
) -> None:
    """Losslessly crop and rotate a PDF page via Swift CoreGraphics."""
    if rotate_cw not in (0, 90, -90, 180, 270):
        raise ValueError(
            f"Unsupported rotation {rotate_cw}; choose from 0, 90, -90, 180, 270"
        )
    crop_x, crop_y, crop_w, crop_h = crop

    swift_code = """
import Foundation
import CoreGraphics

let env = ProcessInfo.processInfo.environment
guard
    let srcPath = env["EXTRACT_SRC_PDF"],
    let pageStr = env["EXTRACT_PAGE"], let pageNum = Int(pageStr),
    let outPath = env["EXTRACT_OUT_PDF"],
    let cxStr = env["EXTRACT_CROP_X"], let cropX = Double(cxStr),
    let cyStr = env["EXTRACT_CROP_Y"], let cropY = Double(cyStr),
    let cwStr = env["EXTRACT_CROP_W"], let cropW = Double(cwStr),
    let chStr = env["EXTRACT_CROP_H"], let cropH = Double(chStr),
    let rotStr = env["EXTRACT_ROTATE"], let rotCW = Int(rotStr)
else {
    fputs("Missing EXTRACT_* environment variables\\n", stderr)
    exit(1)
}

let srcUrl = URL(fileURLWithPath: srcPath) as CFURL
guard let srcDoc = CGPDFDocument(srcUrl), let page = srcDoc.page(at: pageNum) else {
    fputs("Failed to open source PDF or page \\(pageNum)\\n", stderr)
    exit(1)
}

let totalRotCW = ((Int(page.rotationAngle) + rotCW) % 360 + 360) % 360
let outW = (totalRotCW == 90 || totalRotCW == 270) ? cropH : cropW
let outH = (totalRotCW == 90 || totalRotCW == 270) ? cropW : cropH

let outUrl = URL(fileURLWithPath: outPath) as CFURL
var mediaBox = CGRect(x: 0, y: 0, width: outW, height: outH)
guard let ctx = CGContext(outUrl, mediaBox: &mediaBox, nil) else {
    fputs("Failed to create CGPDFContext\\n", stderr)
    exit(1)
}

ctx.beginPDFPage(nil)
ctx.clip(to: mediaBox)

switch totalRotCW {
case 90:
    ctx.translateBy(x: 0, y: CGFloat(outH))
    ctx.rotate(by: -.pi / 2)
case 270:
    ctx.translateBy(x: CGFloat(outW), y: 0)
    ctx.rotate(by: .pi / 2)
case 180:
    ctx.translateBy(x: CGFloat(outW), y: CGFloat(outH))
    ctx.rotate(by: .pi)
default:
    break
}

ctx.translateBy(x: CGFloat(-cropX), y: CGFloat(-cropY))
ctx.drawPDFPage(page)
ctx.endPDFPage()
ctx.closePDF()
"""
    tmp_root = Path(tempfile.gettempdir())
    uid = os.getuid()
    swift_cache = tmp_root / f"extract-pdf-schematic-swift-cache-{uid}"
    clang_cache = tmp_root / f"extract-pdf-schematic-clang-cache-{uid}"
    swift_cache.mkdir(parents=True, exist_ok=True)
    clang_cache.mkdir(parents=True, exist_ok=True)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        dir=out_pdf.parent, prefix=".extract_", suffix=".pdf", delete=False
    ) as tf:
        tmp_out = Path(tf.name)

    try:
        env = os.environ.copy()
        env["CLANG_MODULE_CACHE_PATH"] = str(clang_cache)
        env["EXTRACT_SRC_PDF"] = str(src_pdf.resolve())
        env["EXTRACT_PAGE"] = str(page_num)
        env["EXTRACT_OUT_PDF"] = str(tmp_out.resolve())
        env["EXTRACT_CROP_X"] = f"{crop_x:.6f}"
        env["EXTRACT_CROP_Y"] = f"{crop_y:.6f}"
        env["EXTRACT_CROP_W"] = f"{crop_w:.6f}"
        env["EXTRACT_CROP_H"] = f"{crop_h:.6f}"
        env["EXTRACT_ROTATE"] = str(rotate_cw)

        cmd = ["swift", "-module-cache-path", str(swift_cache), "-e", swift_code]
        res = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            raise RuntimeError(
                f"swift extraction failed ({res.returncode}): {res.stderr.strip()}"
            )
        os.replace(tmp_out, out_pdf)
    except Exception:
        tmp_out.unlink(missing_ok=True)
        raise


def parse_crop_arg(crop_str: str) -> list[float]:
    """Parse `--crop x,y,w,h` validating positive width and height."""
    parts = [float(x.strip()) for x in crop_str.split(",")]
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise argparse.ArgumentTypeError(
            "Crop must be x,y,w,h with positive width and height"
        )
    return parts


def parse_positive_int(val_str: str) -> int:
    """Parse a positive integer (>= 1)."""
    val = int(val_str)
    if val < 1:
        raise argparse.ArgumentTypeError("Value must be >= 1")
    return val


def parse_positive_float(val_str: str) -> float:
    """Parse a strictly positive float (> 0)."""
    val = float(val_str)
    if val <= 0:
        raise argparse.ArgumentTypeError("Value must be > 0")
    return val


def parse_non_negative_float(val_str: str) -> float:
    """Parse a non-negative float (>= 0)."""
    val = float(val_str)
    if val < 0:
        raise argparse.ArgumentTypeError("Value must be >= 0")
    return val


def cmd_inspect(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
        tmp_single = Path(tf.name)
    try:
        preview_path = Path(args.preview) if args.preview else None
        info = get_pdf_info_and_single_page(
            pdf_path, args.page, tmp_single, preview_path, args.scale
        )
        raw = tmp_single.read_bytes()
        mb = info["mediabox"]
        crop_info = detect_crop_box(
            raw, mb[2], mb[3], args.margin, origin_x=mb[0], origin_y=mb[1]
        )
        result = {
            "source": str(pdf_path),
            "page_count": info["page_count"],
            "page": info["page"],
            "label": info["label"],
            "mediabox": mb,
            "rotation": info["rotation"],
            "single_page_bytes": len(raw),
            "images": audit_images(raw),
            "detected_crop": crop_info,
            "neighbors": info["neighbors"],
            "preview": info["preview"],
        }
        print(json.dumps(result, indent=2))
        return 0
    finally:
        tmp_single.unlink(missing_ok=True)


def cmd_extract(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf)
    out_path = Path(args.output)
    if not pdf_path.is_file():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    if args.crop:
        crop = args.crop
        crop_method = "manual"
        footer_max_y = None
    else:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tmp_single = Path(tf.name)
        try:
            info = get_pdf_info_and_single_page(pdf_path, args.page, tmp_single)
            raw = tmp_single.read_bytes()
            mb = info["mediabox"]
            detected = detect_crop_box(
                raw, mb[2], mb[3], args.margin, origin_x=mb[0], origin_y=mb[1]
            )
            crop = detected["crop"]
            crop_method = detected["method"]
            footer_max_y = detected["footer_max_y"]
        finally:
            tmp_single.unlink(missing_ok=True)

    extract_via_coregraphics(pdf_path, args.page, out_path, crop, args.rotate)
    verified = verify_pdf_metadata(out_path)
    preview_info = None
    if args.preview:
        preview_info = render_page_png(out_path, 1, Path(args.preview), args.scale)

    result = {
        "source": str(pdf_path),
        "page": args.page,
        "output": str(out_path),
        "rotate_cw": args.rotate,
        "crop": crop,
        "crop_method": crop_method,
        "footer_max_y": footer_max_y,
        "verified": verified,
        "preview": preview_info,
    }
    print(json.dumps(result, indent=2))

    if verified["page_count"] != 1 or verified["rotation"] != 0:
        print("Error: Extracted PDF failed page_count/rotation check", file=sys.stderr)
        return 1
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1
    info = render_page_png(pdf_path, args.page, Path(args.output), args.scale)
    print(json.dumps(info, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ins = sub.add_parser(
        "inspect", help="Inspect a PDF page and detect its schematic crop box"
    )
    p_ins.add_argument("pdf", help="Source PDF path")
    p_ins.add_argument(
        "--page", type=parse_positive_int, required=True, help="1-based page number"
    )
    p_ins.add_argument(
        "--margin",
        type=parse_non_negative_float,
        default=18.0,
        help="Margin around vector bounds (pt)",
    )
    p_ins.add_argument("--preview", help="Optional output PNG preview path")
    p_ins.add_argument(
        "--scale",
        type=parse_positive_float,
        default=2.0,
        help="Preview render scale (default 2.0 = 144 DPI)",
    )
    p_ins.set_defaults(func=cmd_inspect)

    p_ext = sub.add_parser(
        "extract", help="Losslessly crop and rotate a PDF schematic page"
    )
    p_ext.add_argument("pdf", help="Source PDF path")
    p_ext.add_argument(
        "--page", type=parse_positive_int, required=True, help="1-based page number"
    )
    p_ext.add_argument("--output", required=True, help="Destination PDF path")
    p_ext.add_argument(
        "--rotate",
        type=int,
        default=90,
        choices=[0, 90, -90, 180, 270],
        help="Clockwise rotation in degrees (default: 90)",
    )
    p_ext.add_argument(
        "--crop", type=parse_crop_arg, help="Manual crop box x,y,w,h in source pt"
    )
    p_ext.add_argument(
        "--margin",
        type=parse_non_negative_float,
        default=18.0,
        help="Auto-crop margin around vector bounds (pt)",
    )
    p_ext.add_argument("--preview", help="Optional verification PNG preview path")
    p_ext.add_argument(
        "--scale",
        type=parse_positive_float,
        default=2.0,
        help="Preview render scale (default 2.0)",
    )
    p_ext.set_defaults(func=cmd_extract)

    p_ren = sub.add_parser("render", help="Render a PDF page to PNG")
    p_ren.add_argument("pdf", help="PDF path")
    p_ren.add_argument(
        "--page",
        type=parse_positive_int,
        default=1,
        help="1-based page number (default: 1)",
    )
    p_ren.add_argument("--output", required=True, help="Output PNG path")
    p_ren.add_argument(
        "--scale",
        type=parse_positive_float,
        default=2.0,
        help="Render scale (default 2.0)",
    )
    p_ren.set_defaults(func=cmd_render)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
