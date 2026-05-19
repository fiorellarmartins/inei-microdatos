"""
Update bundled catalog and variable index with ENAHO 2025 data.

Run from the repo root:
    python3 scripts/update_2025.py

What it does:
  1. Re-crawls ENAHO 2025 from the live portal (picks up the new Anual period)
  2. Patches src/inei_microdatos/data/catalog.json with the fresh 2025 data
  3. Builds variable index entries for all ENAHO 2025 modules
  4. Merges into src/inei_microdatos/data/variable_index.json.gz
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from inei_microdatos.catalog import build_catalog, load_catalog, save_catalog
from inei_microdatos.client import INEIClient
from inei_microdatos.variables import build_index, save_index, _read_index_file

BUNDLED_CATALOG = Path("src/inei_microdatos/data/catalog.json")
BUNDLED_INDEX = Path("src/inei_microdatos/data/variable_index.json.gz")


def patch_catalog_year(bundled: list[dict], fresh: list[dict], year: str) -> list[dict]:
    """Replace year data in bundled catalog with fresh data for matching surveys.

    Skips "Anterior" entries — they only hold pre-2004 data and should never
    receive years from a modern crawl.
    """
    fresh_by_value = {e["value"]: e for e in fresh}

    for entry in bundled:
        if "Anterior" in entry.get("category", ""):
            continue
        val = entry["value"]
        if val in fresh_by_value:
            fresh_years = fresh_by_value[val]["years"]
            if year in fresh_years:
                entry["years"][year] = fresh_years[year]
                print(f"  Patched {entry['label'][:60]} — {year}: {list(fresh_years[year].keys())}")

    return bundled


def main():
    print("Step 1: Crawling ENAHO 2025 from portal...")
    client = INEIClient()
    fresh = build_catalog(client=client, surveys=["enaho"], years=(2025, 2025))
    print(f"  Got {len(fresh)} survey entries for 2025")

    for e in fresh:
        if "2025" in e["years"]:
            periods = list(e["years"]["2025"].keys())
            print(f"  {e['label'][:60]}: {periods}")

    print("\nStep 2: Patching bundled catalog...")
    bundled = load_catalog(BUNDLED_CATALOG)
    bundled = patch_catalog_year(bundled, fresh, "2025")
    save_catalog(bundled, BUNDLED_CATALOG)
    print(f"  Saved to {BUNDLED_CATALOG}")

    print("\nStep 3: Building variable index for ENAHO 2025...")
    # Filter to only ENAHO 2025 entries from the freshly patched catalog
    from inei_microdatos.catalog import filter_catalog
    enaho_2025 = filter_catalog(bundled, survey="enaho", year_min=2025, year_max=2025)

    new_entries = build_index(enaho_2025, dest=BUNDLED_INDEX, workers=4)
    print(f"  Indexed {len(new_entries)} total modules in bundled index")

    total_vars = sum(len(e["variables"]) for e in new_entries)
    print(f"  Total variables: {total_vars:,}")
    print(f"  Saved to {BUNDLED_INDEX}")
    print("\nDone. Review the changes, then bump version in pyproject.toml and commit.")


if __name__ == "__main__":
    main()
