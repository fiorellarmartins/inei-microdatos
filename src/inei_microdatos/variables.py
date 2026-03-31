"""Variable index — search across surveys, modules, and years."""

from __future__ import annotations

import gzip
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from inei_microdatos.client import DOWNLOAD_BASE

_BUNDLED_INDEX = Path(__file__).parent / "data" / "variable_index.json.gz"
_USER_INDEX = Path.home() / ".inei-microdatos" / "variable_index.json.gz"


def search(
    query: str,
    index: Optional[list] = None,
    survey: Optional[str] = None,
    year: Optional[str] = None,
    module: Optional[str] = None,
    exact: bool = False,
) -> List[dict]:
    """Search for variables by name or label.

    Args:
        query: Search string — matched against variable name and label.
        index: Variable index (loaded if not provided).
        survey: Filter to this survey (substring match).
        year: Filter to this year.
        module: Filter to this module (substring match).
        exact: If True, match variable name exactly (case-insensitive).

    Returns:
        List of matches, each with keys: survey, year, period, module_code,
        module_name, format, variable, label, value_labels (if any).
    """
    if index is None:
        index = load_index()

    query_lower = query.lower()
    results = []

    for entry in index:
        if survey and survey.lower() not in entry["survey"].lower():
            continue
        if year and entry["year"] != year:
            continue
        if module and module.lower() not in entry["module_name"].lower():
            continue

        for var in entry["variables"]:
            name = var["name"] or ""
            label = var.get("label") or ""

            if exact:
                if name.lower() == query_lower:
                    results.append(_make_result(entry, var))
            else:
                if query_lower in name.lower() or query_lower in label.lower():
                    results.append(_make_result(entry, var))

    return results


def search_across_years(
    variable: str,
    index: Optional[list] = None,
    survey: Optional[str] = None,
) -> Dict[str, List[dict]]:
    """Track a variable across years — shows when it appears, disappears, or changes.

    Args:
        variable: Variable name (exact match, case-insensitive).
        index: Variable index.
        survey: Filter to this survey.

    Returns:
        Dict keyed by year, each value a list of modules containing the variable.
    """
    matches = search(variable, index=index, survey=survey, exact=True)
    by_year = {}
    for m in matches:
        yr = m["year"]
        if yr not in by_year:
            by_year[yr] = []
        by_year[yr].append(m)
    return dict(sorted(by_year.items()))


def load_index(path: Optional[str | Path] = None) -> list:
    """Load the variable index.

    Checks user index first, then bundled, merges both.
    """
    entries = []

    # Bundled index
    if _BUNDLED_INDEX.exists():
        entries.extend(_read_index_file(_BUNDLED_INDEX))

    # User index (from `index` command) — merge on top
    user_path = Path(path) if path else _USER_INDEX
    if user_path.exists():
        user_entries = _read_index_file(user_path)
        # Deduplicate by (survey, year, period, module_code)
        seen = set()
        for e in entries:
            seen.add((e["survey"], e["year"], e["period"], e["module_code"]))
        for e in user_entries:
            key = (e["survey"], e["year"], e["period"], e["module_code"])
            if key not in seen:
                entries.append(e)
                seen.add(key)

    if not entries:
        raise FileNotFoundError(
            "No variable index found. The bundled index may not include this survey yet. "
            "Run 'inei-microdatos index --survey <name>' to build one."
        )

    return entries


def save_index(entries: list, path: str | Path) -> None:
    """Save variable index as gzipped JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, separators=(",", ":"))


def build_index(
    catalog: list,
    dest: str | Path = _USER_INDEX,
    workers: int = 4,
    progress: bool = True,
) -> list:
    """Build variable index by downloading modules in parallel, extracting metadata, and deleting.

    Downloads each ZIP, reads STATA/SPSS metadata, caches variable info, deletes the ZIP.
    Max disk usage: ~workers ZIPs at a time.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from tqdm import tqdm

    entries = []
    modules = _collect_modules(catalog)

    bar = tqdm(total=len(modules), desc="Indexing", disable=not progress)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_index_one_module, mod): mod for mod in modules}
        for future in as_completed(futures):
            bar.update(1)
            try:
                entry = future.result()
                if entry:
                    entries.append(entry)
                    bar.set_postfix(indexed=len(entries))
            except Exception:
                pass

    bar.close()
    save_index(entries, dest)
    return entries


def _collect_modules(catalog: list) -> list:
    """Flatten catalog into a list of module descriptors for indexing."""
    modules = []
    for entry in catalog:
        for year, year_data in entry["years"].items():
            for period_label, period_data in year_data.items():
                for mod in period_data["modules"]:
                    code = mod.get("stata_code") or mod.get("spss_code")
                    if not code:
                        continue
                    fmt = "STATA" if mod.get("stata_code") else "SPSS"
                    alt_code = mod.get("spss_code") if fmt == "STATA" else mod.get("stata_code")
                    modules.append({
                        "survey": entry["label"],
                        "category": entry["category"],
                        "year": year,
                        "period": period_label,
                        "module_code": code,
                        "module_name": mod.get("module_name", ""),
                        "format": fmt,
                        "alt_code": alt_code,
                    })
    return modules


def _index_one_module(mod_info: dict) -> Optional[dict]:
    """Download one module ZIP, extract metadata, delete ZIP. Returns index entry."""
    import requests
    import zipfile
    import io

    code = mod_info["module_code"]
    fmt = mod_info["format"]
    ext = ".dta" if fmt == "STATA" else ".sav"
    url = f"{DOWNLOAD_BASE}{fmt}/{code}.zip"

    # Pick the smaller format when both are available
    alt_code = mod_info.get("alt_code")
    if alt_code:
        alt_fmt = "SPSS" if fmt == "STATA" else "STATA"
        try:
            h1 = requests.head(url, timeout=10)
            h2 = requests.head(f"{DOWNLOAD_BASE}{alt_fmt}/{alt_code}.zip", timeout=10)
            s1 = int(h1.headers.get("content-length", 0))
            s2 = int(h2.headers.get("content-length", 0))
            if s2 > 0 and s2 < s1:
                url = f"{DOWNLOAD_BASE}{alt_fmt}/{alt_code}.zip"
                fmt = alt_fmt
                ext = ".dta" if fmt == "STATA" else ".sav"
        except requests.RequestException:
            pass

    r = requests.get(url, timeout=300)
    r.raise_for_status()

    zip_bytes = io.BytesIO(r.content)
    with zipfile.ZipFile(zip_bytes) as zf:
        for name in zf.namelist():
            if name.lower().endswith(ext):
                return _extract_metadata(zf, name, ext, mod_info)
    return None


def _extract_metadata(zf, filename: str, ext: str, mod_info: dict) -> dict:
    """Extract variable metadata from a data file inside a ZIP."""
    import pyreadstat
    import tempfile
    import os

    with zf.open(filename) as f:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name

    try:
        reader = pyreadstat.read_dta if ext == ".dta" else pyreadstat.read_sav
        _, meta = reader(tmp_path, metadataonly=True)
    finally:
        os.unlink(tmp_path)

    variables = []
    for col in meta.column_names:
        var_entry = {
            "name": col,
            "label": meta.column_names_to_labels.get(col, ""),
        }
        # Include value labels if available (compact: just the label set name)
        if hasattr(meta, "variable_to_label"):
            vl_name = meta.variable_to_label.get(col)
            if vl_name and vl_name in meta.value_labels:
                vl = meta.value_labels[vl_name]
                # Only include if small enough (< 20 values)
                if len(vl) <= 20:
                    var_entry["values"] = {str(k): v for k, v in vl.items()}

        variables.append(var_entry)

    return {
        "survey": mod_info["survey"],
        "category": mod_info["category"],
        "year": mod_info["year"],
        "period": mod_info["period"],
        "module_code": mod_info["module_code"],
        "module_name": mod_info["module_name"],
        "format": mod_info["format"],
        "n_rows": meta.number_rows,
        "variables": variables,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _make_result(entry: dict, var: dict) -> dict:
    return {
        "survey": entry["survey"],
        "category": entry.get("category", ""),
        "year": entry["year"],
        "period": entry["period"],
        "module_code": entry["module_code"],
        "module_name": entry["module_name"],
        "variable": var["name"],
        "label": var.get("label", ""),
        "values": var.get("values"),
    }


def _read_index_file(path: Path) -> list:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    else:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
