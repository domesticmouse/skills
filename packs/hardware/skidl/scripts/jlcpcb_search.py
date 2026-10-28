#!/usr/bin/env python3
"""
Query live JLCPCB SMT component catalog (with jlcsearch fallback) for stock,
Basic/Extended library status, and pricing tiers.

Usage:
    python3 .agents/skills/skidl/scripts/jlcpcb_search.py "C149504" "TL074 SOIC-14" "10uF D6.3xL5.4mm"
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def query_jlcpcb(keyword: str, page_size: int = 8) -> list[dict]:
    """Query JLCPCB's internal component search endpoint."""
    url = (
        "https://jlcpcb.com/api/overseas-pcb-order/v1/"
        "shoppingCart/smtGood/selectSmtComponentList/v2"
    )
    payload = json.dumps(
        {
            "keyword": keyword,
            "currentPage": 1,
            "pageSize": page_size,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Origin": "https://jlcpcb.com",
            "Referer": "https://jlcpcb.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        page_info = (data.get("data") or {}).get("componentPageInfo") or {}
        items = page_info.get("list") or []

    results = []
    for item in items:
        prices = item.get("componentPrices") or []
        unit_price = prices[0].get("productPrice") if prices else None
        lib_type = item.get("componentLibraryType")
        preferred = item.get("preferredComponentFlag")
        if lib_type == "base":
            jlc_class = "Basic"
        elif preferred:
            jlc_class = "Preferred Extended"
        else:
            jlc_class = "Extended"

        results.append(
            {
                "lcsc": item.get("componentCode"),
                "mpn": item.get("componentModelEn"),
                "brand": item.get("componentBrandEn"),
                "package": item.get("componentSpecificationEn"),
                "class": jlc_class,
                "stock": item.get("stockCount") or 0,
                "unit_price_usd": unit_price,
                "description": item.get("describe"),
            }
        )
    return results


def query_jlcsearch(keyword: str, limit: int = 8) -> list[dict]:
    """Fallback query using jlcsearch.tscircuit.com JSON API."""
    q = urllib.parse.quote(keyword)
    url = f"https://jlcsearch.tscircuit.com/api/search?q={q}&limit={limit}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        items = data.get("components") or (data if isinstance(data, list) else [])

    results = []
    for item in items:
        lcsc_num = item.get("lcsc")
        results.append(
            {
                "lcsc": f"C{lcsc_num}" if lcsc_num else None,
                "mpn": item.get("mfr"),
                "brand": None,
                "package": item.get("package"),
                "class": "Basic" if item.get("basic") else "Extended",
                "stock": item.get("stock") or 0,
                "unit_price_usd": item.get("price"),
                "description": item.get("description"),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search JLCPCB parts catalog for live stock and pricing."
    )
    parser.add_argument("keywords", nargs="+", help="Part numbers or search terms")
    parser.add_argument(
        "--in-stock-only",
        action="store_true",
        help="Filter out components with 0 stock",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Maximum results per keyword (default: 8)",
    )
    args = parser.parse_args()

    output = {}
    for kw in args.keywords:
        try:
            items = query_jlcpcb(kw, page_size=args.limit)
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as err:
            print(
                f"[warn] JLCPCB API failed for '{kw}' ({err}); trying jlcsearch...",
                file=sys.stderr,
            )
            try:
                items = query_jlcsearch(kw, limit=args.limit)
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as err2:
                print(
                    f"[error] jlcsearch fallback also failed for '{kw}' ({err2}). "
                    "Ensure network access is enabled (e.g. run outside the sandbox).",
                    file=sys.stderr,
                )
                return 1

        if args.in_stock_only:
            items = [i for i in items if (i.get("stock") or 0) > 0]
        output[kw] = items

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
