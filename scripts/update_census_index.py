"""Refresh bundled census search metadata while preserving survey entries."""

import argparse
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from inei_microdatos.catalog import load_catalog, filter_catalog
from inei_microdatos.census import CENSUS_LABEL
from inei_microdatos.variables import build_index, save_index, _read_index_file, _collect_modules


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Reuse downloaded census XLSX files")
    args = parser.parse_args()
    data = ROOT / "src/inei_microdatos/data"
    catalog = filter_catalog(load_catalog(data / "catalog.json"), survey="censo")
    expected = {m["module_code"] for m in _collect_modules(catalog)}
    with tempfile.TemporaryDirectory(prefix="inei-census-index-build-") as tmp:
        fresh = build_index(catalog, dest=Path(tmp) / "index.json.gz", data_dir=args.data_dir,
                            progress=sys.stderr.isatty())
    actual = {e["module_code"] for e in fresh}
    if not expected or actual != expected or len(actual) != len(fresh):
        raise RuntimeError(f"Incomplete census index; missing: {sorted(expected - actual)}")
    path = data / "variable_index.json.gz"
    existing = _read_index_file(path)
    preserved = [e for e in existing if e["survey"] != CENSUS_LABEL]
    fresh.sort(key=lambda e: (e["year"], e["period"], e["module_code"]))
    save_index(preserved + fresh, path)
    print(f"Preserved {len(preserved)} survey modules; indexed {len(fresh)} census modules")
    for year in sorted({e["year"] for e in fresh}):
        counts = Counter(v["kind"] for e in fresh if e["year"] == year for v in e["variables"])
        print(year, dict(counts))


if __name__ == "__main__":
    main()
