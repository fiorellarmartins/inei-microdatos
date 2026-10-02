"""Refresh only population and housing census tables in the bundled catalog (run from repo root)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from inei_microdatos.census import CENSUS_VALUE, build_census_catalog


def main():
    path = Path(__file__).resolve().parent.parent / "src/inei_microdatos/data/catalog.json"
    fresh = build_census_catalog()
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Preserve the timestamp of the ASP crawl; census has its own timestamp.
    payload["catalog"] = [e for e in payload["catalog"] if e["value"] not in (CENSUS_VALUE, "CPV2025-TABULADOS")] + [fresh]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for year, periods in fresh["years"].items():
        print(f"{year}: {len(periods['Unico']['modules'])} downloadable modules ({periods['Unico']['access']})")


if __name__ == "__main__":
    main()
