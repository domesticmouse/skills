#!/usr/bin/env python3
"""Render high-resolution overlapping tiles, zoom crops, and manual searches from PDFs on macOS."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _swift_env_and_cache() -> tuple[dict[str, str], str]:
    uid = os.getuid() if hasattr(os, "getuid") else 0
    tmp = tempfile.gettempdir()
    swift_cache = os.path.join(tmp, f"describe-schematic-pdf-swift-cache-{uid}")
    clang_cache = os.path.join(tmp, f"describe-schematic-pdf-clang-cache-{uid}")
    os.makedirs(swift_cache, exist_ok=True)
    os.makedirs(clang_cache, exist_ok=True)
    env = os.environ.copy()
    env["CLANG_MODULE_CACHE_PATH"] = clang_cache
    return env, swift_cache


def run_swift(swift_code: str, payload: dict[str, object]) -> str:
    """Execute inline Swift via /usr/bin/swift using user-scoped temp caches."""
    env, swift_cache = _swift_env_and_cache()
    cmd = ["swift", "-module-cache-path", swift_cache, "-e", swift_code]
    res = subprocess.run(
        cmd,
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"swift failed ({res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
        )
    return res.stdout


def cmd_tile(args: argparse.Namespace) -> None:
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if args.page < 1:
        raise ValueError("--page must be >= 1")
    if args.cols < 1 or args.rows < 1:
        raise ValueError("--cols and --rows must be >= 1")
    if not math.isfinite(args.scale) or args.scale <= 0:
        raise ValueError("--scale must be a finite number > 0")
    if not math.isfinite(args.overlap) or args.overlap < 0:
        raise ValueError("--overlap must be a finite number >= 0")

    stem = args.stem if args.stem is not None else pdf_path.stem
    if not stem or Path(stem).name != stem or stem in {".", ".."}:
        raise ValueError(f"Invalid --stem: {stem!r}")

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    swift_code = r"""
import Foundation
import PDFKit
import AppKit

let inputData = FileHandle.standardInput.readDataToEndOfFile()
guard let payloadIn = try JSONSerialization.jsonObject(with: inputData) as? [String: Any],
      let pdfPath = payloadIn["pdf"] as? String,
      let outDir = payloadIn["out_dir"] as? String,
      let stem = payloadIn["stem"] as? String,
      let pageNum = payloadIn["page"] as? Int,
      let cols = payloadIn["cols"] as? Int,
      let rows = payloadIn["rows"] as? Int,
      let scaleVal = (payloadIn["scale"] as? NSNumber)?.doubleValue,
      let overlapVal = (payloadIn["overlap"] as? NSNumber)?.doubleValue else {
    fputs("Invalid JSON payload on stdin\n", stderr)
    exit(1)
}
let scale = CGFloat(scaleVal)
let overlap = CGFloat(overlapVal)

guard let doc = PDFDocument(url: URL(fileURLWithPath: pdfPath)) else {
    fputs("Failed to open PDF: \(pdfPath)\n", stderr)
    exit(1)
}
let pageCount = doc.pageCount
guard pageNum >= 1 && pageNum <= pageCount, let page = doc.page(at: pageNum - 1) else {
    fputs("Page \(pageNum) out of range (1..\(pageCount))\n", stderr)
    exit(1)
}

let bounds = page.bounds(for: .mediaBox)
let rot = ((page.rotation % 360) + 360) % 360
let pageW = (rot == 90 || rot == 270) ? bounds.height : bounds.width
let pageH = (rot == 90 || rot == 270) ? bounds.width : bounds.height
let tileW = pageW / CGFloat(cols)
let tileH = pageH / CGFloat(rows)
var tiles: [[String: Any]] = []

for r in 0..<rows {
    for c in 0..<cols {
        try autoreleasepool {
            let x0 = max(0, CGFloat(c) * tileW - overlap)
            let x1 = min(pageW, CGFloat(c + 1) * tileW + overlap)
            let yTop = pageH - CGFloat(r) * tileH
            let yBot = pageH - CGFloat(r + 1) * tileH
            let y0 = max(0, yBot - overlap)
            let y1 = min(pageH, yTop + overlap)
            let cropW = max(1e-3, x1 - x0)
            let cropH = max(1e-3, y1 - y0)
            let pxW = max(1, Int(ceil(cropW * scale)))
            let pxH = max(1, Int(ceil(cropH * scale)))

            guard let cs = CGColorSpace(name: CGColorSpace.sRGB),
                  let ctx = CGContext(
                    data: nil, width: pxW, height: pxH, bitsPerComponent: 8, bytesPerRow: 0,
                    space: cs, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                  ) else {
                fputs("Failed to allocate CGContext\n", stderr)
                exit(1)
            }
            ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
            ctx.fill(CGRect(x: 0, y: 0, width: pxW, height: pxH))
            ctx.scaleBy(x: scale, y: scale)
            ctx.translateBy(x: -x0, y: -y0)
            page.draw(with: .mediaBox, to: ctx)

            let outPath = "\(outDir)/\(stem)_r\(r)_c\(c).png"
            guard let cgImg = ctx.makeImage(),
                  let png = NSBitmapImageRep(cgImage: cgImg).representation(using: .png, properties: [:]) else {
                fputs("Failed to encode PNG\n", stderr)
                exit(1)
            }
            try png.write(to: URL(fileURLWithPath: outPath))
            tiles.append([
                "row": r,
                "col": c,
                "pdf_rect": [Double(x0), Double(y0), Double(cropW), Double(cropH)],
                "width_px": pxW,
                "height_px": pxH,
                "path": outPath,
            ])
        }
    }
}

let payload: [String: Any] = [
    "pdf": pdfPath,
    "page": pageNum,
    "page_count": pageCount,
    "rotation": rot,
    "page_size": [Double(pageW), Double(pageH)],
    "mediabox": [Double(bounds.minX), Double(bounds.minY), Double(bounds.width), Double(bounds.height)],
    "scale": Double(scale),
    "tiles": tiles,
]
let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
print(String(data: data, encoding: .utf8)!)
"""
    out = run_swift(
        swift_code,
        {
            "pdf": str(pdf_path),
            "out_dir": str(out_dir),
            "stem": stem,
            "page": args.page,
            "cols": args.cols,
            "rows": args.rows,
            "scale": args.scale,
            "overlap": args.overlap,
        },
    )
    print(out.strip())


def cmd_crop(args: argparse.Namespace) -> None:
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if args.page < 1:
        raise ValueError("--page must be >= 1")
    if not math.isfinite(args.scale) or args.scale <= 0:
        raise ValueError("--scale must be a finite number > 0")

    parts = [p.strip() for p in args.rect.split(",")]
    if len(parts) != 4:
        raise ValueError("--rect must be x,y,w,h in PDF points (origin bottom-left)")
    x, y, w, h = (float(v) for v in parts)
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        raise ValueError("--rect values must be finite numbers")
    if w <= 0 or h <= 0:
        raise ValueError("Crop width and height must be positive")

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    swift_code = r"""
import Foundation
import PDFKit
import AppKit

let inputData = FileHandle.standardInput.readDataToEndOfFile()
guard let payloadIn = try JSONSerialization.jsonObject(with: inputData) as? [String: Any],
      let pdfPath = payloadIn["pdf"] as? String,
      let outPath = payloadIn["output"] as? String,
      let pageNum = payloadIn["page"] as? Int,
      let rxVal = (payloadIn["x"] as? NSNumber)?.doubleValue,
      let ryVal = (payloadIn["y"] as? NSNumber)?.doubleValue,
      let rwVal = (payloadIn["w"] as? NSNumber)?.doubleValue,
      let rhVal = (payloadIn["h"] as? NSNumber)?.doubleValue,
      let scaleVal = (payloadIn["scale"] as? NSNumber)?.doubleValue else {
    fputs("Invalid JSON payload on stdin\n", stderr)
    exit(1)
}
let rx = CGFloat(rxVal)
let ry = CGFloat(ryVal)
let rw = CGFloat(rwVal)
let rh = CGFloat(rhVal)
let scale = CGFloat(scaleVal)

guard let doc = PDFDocument(url: URL(fileURLWithPath: pdfPath)) else {
    fputs("Failed to open PDF: \(pdfPath)\n", stderr)
    exit(1)
}
let pageCount = doc.pageCount
guard pageNum >= 1 && pageNum <= pageCount, let page = doc.page(at: pageNum - 1) else {
    fputs("Page \(pageNum) out of range (1..\(pageCount))\n", stderr)
    exit(1)
}

let pxW = max(1, Int(ceil(rw * scale)))
let pxH = max(1, Int(ceil(rh * scale)))
guard let cs = CGColorSpace(name: CGColorSpace.sRGB),
      let ctx = CGContext(
        data: nil, width: pxW, height: pxH, bitsPerComponent: 8, bytesPerRow: 0,
        space: cs, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
      ) else {
    fputs("Failed to allocate CGContext\n", stderr)
    exit(1)
}
ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
ctx.fill(CGRect(x: 0, y: 0, width: pxW, height: pxH))
ctx.scaleBy(x: scale, y: scale)
ctx.translateBy(x: -rx, y: -ry)
page.draw(with: .mediaBox, to: ctx)

guard let cgImg = ctx.makeImage(),
      let png = NSBitmapImageRep(cgImage: cgImg).representation(using: .png, properties: [:]) else {
    fputs("Failed to encode PNG\n", stderr)
    exit(1)
}
try png.write(to: URL(fileURLWithPath: outPath))

let payload: [String: Any] = [
    "pdf": pdfPath,
    "page": pageNum,
    "rect": [Double(rx), Double(ry), Double(rw), Double(rh)],
    "scale": Double(scale),
    "width_px": pxW,
    "height_px": pxH,
    "output": outPath,
]
let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
print(String(data: data, encoding: .utf8)!)
"""
    out = run_swift(
        swift_code,
        {
            "pdf": str(pdf_path),
            "output": str(out_path),
            "page": args.page,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "scale": args.scale,
        },
    )
    print(out.strip())


def cmd_search_manual(args: argparse.Namespace) -> None:
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if args.max_per_term < 1:
        raise ValueError("--max-per-term must be >= 1")

    swift_code = r"""
import Foundation
import PDFKit

let inputData = FileHandle.standardInput.readDataToEndOfFile()
guard let payloadIn = try JSONSerialization.jsonObject(with: inputData) as? [String: Any],
      let pdfPath = payloadIn["pdf"] as? String,
      let maxPerTerm = payloadIn["max_per_term"] as? Int,
      let terms = payloadIn["terms"] as? [String] else {
    fputs("Invalid JSON payload on stdin\n", stderr)
    exit(1)
}

guard let doc = PDFDocument(url: URL(fileURLWithPath: pdfPath)) else {
    fputs("Failed to open PDF: \(pdfPath)\n", stderr)
    exit(1)
}
print("=== \(pdfPath) (\(doc.pageCount) pages) ===")
for i in 0..<doc.pageCount {
    guard let txt = doc.page(at: i)?.string else { continue }
    let lines = txt.components(separatedBy: .newlines)
    for t in terms {
        let hits = lines.filter { $0.localizedCaseInsensitiveContains(t) }
        for h in hits.prefix(maxPerTerm) {
            let trimmed = h.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                print("p.\(i + 1) [\(t)]: \(trimmed)")
            }
        }
    }
}
"""
    out = run_swift(
        swift_code,
        {
            "pdf": str(pdf_path),
            "max_per_term": args.max_per_term,
            "terms": list(args.terms),
        },
    )
    print(out.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_tile = sub.add_parser(
        "tile", help="Render overlapping high-resolution tiles of a schematic PDF page"
    )
    p_tile.add_argument("pdf", help="Path to schematic PDF")
    p_tile.add_argument(
        "--out-dir", required=True, help="Directory for output PNG tiles"
    )
    p_tile.add_argument("--stem", help="Filename stem for tiles (default: PDF stem)")
    p_tile.add_argument(
        "--page", type=int, default=1, help="1-based PDF page number (default: 1)"
    )
    p_tile.add_argument("--cols", type=int, default=3, help="Grid columns (default: 3)")
    p_tile.add_argument("--rows", type=int, default=2, help="Grid rows (default: 2)")
    p_tile.add_argument(
        "--scale", type=float, default=4.5, help="Render scale factor (default: 4.5)"
    )
    p_tile.add_argument(
        "--overlap",
        type=float,
        default=35.0,
        help="Tile overlap in PDF points (default: 35)",
    )
    p_tile.set_defaults(func=cmd_tile)

    p_crop = sub.add_parser(
        "crop",
        help="Render a zoomed crop in upright PDF coordinates (origin bottom-left)",
    )
    p_crop.add_argument("pdf", help="Path to schematic PDF")
    p_crop.add_argument("--rect", required=True, help="Crop rect x,y,w,h in PDF points")
    p_crop.add_argument("--output", required=True, help="Output PNG path")
    p_crop.add_argument(
        "--page", type=int, default=1, help="1-based PDF page number (default: 1)"
    )
    p_crop.add_argument(
        "--scale", type=float, default=12.0, help="Render scale factor (default: 12.0)"
    )
    p_crop.set_defaults(func=cmd_crop)

    p_search = sub.add_parser(
        "search-manual", help="Search a manual PDF for BOM/calibration terms"
    )
    p_search.add_argument("pdf", help="Path to manual PDF")
    p_search.add_argument("terms", nargs="+", help="Case-insensitive search terms")
    p_search.add_argument(
        "--max-per-term",
        type=int,
        default=4,
        help="Max lines per page/term (default: 4)",
    )
    p_search.set_defaults(func=cmd_search_manual)

    args = parser.parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
