"""Read INEI microdata into pandas DataFrames."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Union

from inei_microdatos.client import DOWNLOAD_BASE


def read_module(
    source: Union[str, Path],
    tables: Optional[List[str]] = None,
    fmt: Optional[str] = None,
) -> Dict[str, "pandas.DataFrame"]:
    """Read a module ZIP into a dict of DataFrames.

    Args:
        source: Path to a ZIP file, or a download code like "968-Modulo1629".
            If a code is given, downloads it first.
        tables: Optional list of table names to read (e.g. ["RECH0", "RECH1"]).
            If None, reads all data files.
        fmt: Format hint — "csv", "stata", "spss". Auto-detected from file
            extensions if not specified.

    Returns:
        Dict mapping table name (without year suffix) to DataFrame.
        E.g. {"RECH0": df1, "RECH1": df2, ...}
    """
    import pandas as pd

    source = str(source)

    # If it's a download code (not a file path), download to a temp location
    if not source.endswith(".zip") and "/" not in source and "\\" not in source:
        source = _download_to_temp(source, fmt)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    result = {}

    with zipfile.ZipFile(path) as zf:
        data_files = _find_data_files(zf.namelist())

        for name, detected_fmt, table_name in data_files:
            if tables and not any(t.lower() in table_name.lower() for t in tables):
                continue

            with zf.open(name) as f:
                data = io.BytesIO(f.read())

            use_fmt = fmt or detected_fmt
            df = _read_data(data, use_fmt, name)
            result[table_name] = df

    return result


def read_catalog_entry(
    catalog_entry: dict,
    year: str,
    period: Optional[str] = None,
    module: Optional[str] = None,
    fmt: str = "csv",
    dest: Optional[Union[str, Path]] = None,
) -> Dict[str, "pandas.DataFrame"]:
    """Read data directly from a catalog entry, downloading as needed.

    Args:
        catalog_entry: A single entry from the catalog.
        year: Year to read.
        period: Period label (if None, uses the first available period).
        module: Module name substring to filter (if None, reads first module).
        fmt: Preferred format — "csv", "stata", "spss".
        dest: Cache directory for downloads. If None, uses temp dir.

    Returns:
        Dict mapping table name to DataFrame.
    """
    years = catalog_entry.get("years", {})
    if year not in years:
        available = sorted(years.keys())
        raise ValueError(f"Year {year} not available. Available: {available}")

    year_data = years[year]

    if period:
        period_data = next(
            (v for k, v in year_data.items() if period.lower() in k.lower()),
            None,
        )
        if not period_data:
            raise ValueError(f"Period '{period}' not found. Available: {list(year_data.keys())}")
    else:
        period_data = next(iter(year_data.values()))

    mods = period_data["modules"]
    if module:
        mods = [m for m in mods if module.lower() in m["module_name"].lower()]

    if not mods:
        raise ValueError("No matching modules found.")

    mod = mods[0]
    fmt_upper = fmt.upper()
    code_key = {"CSV": "csv_code", "STATA": "stata_code", "SPSS": "spss_code"}

    # Try preferred format, then fallback
    code = None
    actual_fmt = fmt_upper
    for try_fmt in [fmt_upper, "STATA", "SPSS", "CSV"]:
        code = mod.get(code_key.get(try_fmt, ""))
        if code:
            actual_fmt = try_fmt
            break

    if not code:
        raise ValueError(f"No download code available for module {mod['module_name']}")

    url = f"{DOWNLOAD_BASE}{actual_fmt}/{code}.zip"

    if dest:
        dest_path = Path(dest) / f"{code}.zip"
    else:
        import tempfile
        dest_path = Path(tempfile.gettempdir()) / "inei_microdatos" / f"{code}.zip"

    if not dest_path.exists():
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        import requests
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)

    return read_module(dest_path, fmt=actual_fmt.lower())


def list_tables(source: Union[str, Path]) -> List[dict]:
    """List data tables inside a module ZIP without reading them.

    Returns:
        List of dicts with keys: name, format, size_bytes, full_path.
    """
    path = Path(source)
    result = []
    with zipfile.ZipFile(path) as zf:
        for name, detected_fmt, table_name in _find_data_files(zf.namelist()):
            info = zf.getinfo(name)
            result.append({
                "name": table_name,
                "format": detected_fmt,
                "size_bytes": info.file_size,
                "full_path": name,
            })
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_DATA_EXTENSIONS = {
    ".csv": "csv",
    ".dta": "stata",
    ".sav": "spss",
}


def _find_data_files(names: List[str]) -> List[tuple]:
    """Return (zip_path, format, table_name) for each data file."""
    results = []
    for name in names:
        lower = name.lower()
        for ext, fmt in _DATA_EXTENSIONS.items():
            if lower.endswith(ext):
                # Table name: strip path, extension, and year suffix
                basename = Path(name).stem
                # Remove common year suffixes like _2024, _2023
                table = basename
                for suffix_len in [5, 6]:  # _2024 or _02024
                    if len(table) > suffix_len and table[-suffix_len] == "_" and table[-suffix_len + 1:].isdigit():
                        table = table[:-suffix_len]
                        break
                results.append((name, fmt, table))
                break
    return results


def _read_data(data: io.BytesIO, fmt: str, name: str) -> "pandas.DataFrame":
    """Read a data buffer into a DataFrame."""
    import pandas as pd

    fmt = fmt.lower()
    if fmt == "csv":
        # INEI CSVs are UTF-8 with BOM, comma-separated
        try:
            return pd.read_csv(data, encoding="utf-8-sig", low_memory=False)
        except UnicodeDecodeError:
            data.seek(0)
            return pd.read_csv(data, encoding="latin-1", low_memory=False)
    elif fmt == "stata":
        try:
            return pd.read_stata(data)
        except ValueError:
            # INEI STATA files sometimes have duplicate value labels
            # (e.g. same label for different codes). Retry without categoricals.
            data.seek(0)
            return pd.read_stata(data, convert_categoricals=False)
    elif fmt == "spss":
        try:
            return pd.read_spss(data)
        except Exception:
            # read_spss doesn't accept BytesIO in older pandas, write to temp
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as tmp:
                tmp.write(data.read())
                tmp_path = tmp.name
            try:
                return pd.read_spss(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
    else:
        raise ValueError(f"Unknown format: {fmt}")


def _download_to_temp(code: str, fmt: Optional[str] = None) -> str:
    """Download a module by code to a temp directory."""
    import tempfile
    import requests

    fmt = (fmt or "csv").upper()
    # Try preferred format first, then fallback
    for try_fmt in [fmt, "STATA", "SPSS", "CSV"]:
        url = f"{DOWNLOAD_BASE}{try_fmt}/{code}.zip"
        try:
            r = requests.head(url, timeout=10)
            if r.status_code == 200:
                dest = Path(tempfile.gettempdir()) / "inei_microdatos" / f"{code}.zip"
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    r = requests.get(url, timeout=120, stream=True)
                    r.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                return str(dest)
        except requests.RequestException:
            continue

    raise FileNotFoundError(f"Could not find download for code: {code}")
