"""Read INEI microdata into pandas DataFrames."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Union

from inei_microdatos.client import DOWNLOAD_BASE


def read_module(
    source: Union[str, Path],
    tables: Optional[List[str]] = None,
    fmt: Optional[str] = None,
) -> Dict[str, "pandas.DataFrame"]:
    """Read a module ZIP, XLSX workbook, or INEI HTML/SYLK XLS export.

    XLSX sheets retain every row (header=None) because census workbooks contain
    titles, notes, merged headings, and totals rather than rectangular microdata.

    Args:
        source: Path to a ZIP/XLSX/XLS file, or a download code like "968-Modulo1629".
            If a code is given, downloads it first.
        tables: Optional list of table names to read (e.g. ["RECH0", "RECH1"]).
            If None, reads all data files.
        fmt: Format hint — "csv", "stata", "spss", "xlsx", "xls". Auto-detected from file
            extensions if not specified.

    Returns:
        Dict mapping table name (without year suffix) to DataFrame.
        E.g. {"RECH0": df1, "RECH1": df2, ...}
    """
    import pandas as pd

    source = str(source)

    # If it's a download code (not a file path), download to a temp location
    if not source.lower().endswith((".zip", ".xlsx", ".xls")) and "/" not in source and "\\" not in source:
        source = _download_to_temp(source, fmt)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if path.suffix.lower() == ".xls":
        name = _legacy_table_name(path)
        return {name: _read_legacy_excel(path)} if not tables or any(
            t.lower() in name.lower() for t in tables
        ) else {}

    if path.suffix.lower() == ".xlsx":
        with pd.ExcelFile(path, engine="openpyxl") as workbook:
            return {
                name: workbook.parse(name, header=None)
                for name in workbook.sheet_names
                if not tables or any(t.lower() in name.lower() for t in tables)
            }

    result = {}

    with zipfile.ZipFile(path) as zf:
        data_files = _find_data_files(zf.namelist())
        report = json.loads(zf.read("geography.json")) if "geography.json" in zf.namelist() else None
        report_tables = {t["file"]: t for t in report["tables"]} if report else {}

        for name, detected_fmt, table_name in data_files:
            if tables and not any(t.lower() in table_name.lower() for t in tables):
                continue

            with zf.open(name) as f:
                data = io.BytesIO(f.read())

            use_fmt = fmt or detected_fmt
            if report and name in report_tables:
                info = report_tables[name]
                df = pd.read_csv(data, encoding="utf-8", low_memory=False,
                                 dtype={c: "string" for c in info["text_columns"]})
                df.attrs.update(ubigeo=report["ubigeo"], survey_year=report["year"],
                                geography_report=report, geographic_rows=info)
            else:
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
    ubigeo: Optional[str] = None,
) -> Dict[str, "pandas.DataFrame"]:
    """Read data directly from a catalog entry, downloading as needed.

    Args:
        catalog_entry: A single entry from the catalog.
        year: Year to read.
        period: Period label (if None, uses the first available period).
        module: Module name substring to filter (if None, reads first module).
        fmt: Preferred format — "csv", "stata", "spss", "xlsx", "xls".
        dest: Cache directory for downloads. If None, uses temp dir.
        ubigeo: Optional 2/4/6-digit INEI code, where a verified adapter exists.

    Returns:
        Dict mapping table name to DataFrame.
    """
    year = str(year)
    if ubigeo is not None:
        from inei_microdatos.survey_geography import select_geography
        scoped = dict(catalog_entry, years={year: catalog_entry.get("years", {}).get(year, {})})
        if not scoped["years"][year]:
            raise ValueError(f"Year {year} not available")
        catalog_entry = select_geography([scoped], ubigeo)[0]
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
    from inei_microdatos.download import module_download, _download_one

    selected = module_download(mod, fmt)
    if not selected:
        raise ValueError(f"No download available for module {mod['module_name']}")
    url, code, actual_fmt, extension = selected

    if dest:
        dest_path = Path(dest) / f"{code}{extension}"
    else:
        import tempfile
        dest_path = Path(tempfile.gettempdir()) / "inei_microdatos" / f"{code}{extension}"

    status = _download_one(url, dest_path)
    if status == "unavailable":
        from inei_microdatos.geography import GeographyUnavailable
        raise GeographyUnavailable(f"Module {mod['module_name']} has no tables for ubigeo {mod['geography']['code']}")
    if status not in ("ok", "skipped", "empty", "partial"):
        raise OSError(f"Could not download module {mod['module_name']}: {status}")

    frames = read_module(dest_path, fmt=actual_fmt.lower())
    if mod.get("geography", {}).get("names"):
        for frame in frames.values():
            frame.attrs.update(ubigeo=mod["geography"]["code"], census_year=year, geography=mod["geography"]["names"])
    return frames


def list_tables(source: Union[str, Path]) -> List[dict]:
    """List data files inside a ZIP, XLSX sheets, or the table in an INEI XLS export.

    Returns:
        List of dicts with keys: name, format, size_bytes, full_path.
    """
    path = Path(source)
    if path.suffix.lower() == ".xls":
        _read_legacy_excel(path)  # Reject error pages disguised as Excel.
        name = _legacy_table_name(path)
        return [{"name": name, "format": "xls",
                 "size_bytes": path.stat().st_size, "full_path": name}]
    if path.suffix.lower() == ".xlsx":
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(path) as workbook:
            root = ET.fromstring(workbook.read("xl/workbook.xml"))
            rels = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
            targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
            result = []
            for sheet in root.findall(".//{*}sheet"):
                rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                target = targets[rel_id]
                target = target.lstrip("/") if target.startswith("/") else "xl/" + target
                result.append({
                    "name": sheet.attrib["name"], "format": "xlsx",
                    "size_bytes": workbook.getinfo(target).file_size,
                    "full_path": target,
                })
            return result
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


def _legacy_table_name(path: Path) -> str:
    with path.open("rb") as stream:
        return "REDATAM" if stream.read(3) == b"ID;" else "tabDetalle"


def _read_sylk(text: str):
    """Read the cell-value records in INEI exports without executing formulas.

    Preserve title, blank, heading and footer rows. Formatting records and the
    unreliable declared dimensions are ignored; unsupported cell records fail.
    """
    import re
    import pandas as pd
    if not text.rstrip().endswith("\nE"):
        raise ValueError("Incomplete SYLK export")
    cells = {}
    x = y = 1
    for line in text.splitlines():
        if not line.startswith("C;"):
            continue
        coords, separator, value = line.partition(";K")
        if not separator or not re.fullmatch(r"C(?:;[XY][0-9]+)*", coords):
            raise ValueError("Unsupported SYLK cell record")
        for axis, number in re.findall(r";([XY])([0-9]+)", coords):
            if axis == "X":
                x = int(number)
            else:
                y = int(number)
        if x < 1 or y < 1 or x > 256 or y > 65536:
            raise ValueError("Invalid SYLK cell coordinates")
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('""', '"').replace(';;', ';')
        elif re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?", value):
            value = float(value)
        else:
            raise ValueError("Unsupported SYLK cell value")
        cells[y - 1, x - 1] = value
    if not cells:
        raise ValueError("No cells in SYLK export")
    rows = max(row for row, col in cells) + 1
    cols = max(col for row, col in cells) + 1
    if rows * cols > 1_000_000:
        raise ValueError("SYLK frequency table is too large")
    frame = pd.DataFrame(index=range(rows), columns=range(cols), dtype=object)
    for (row, col), value in cells.items():
        frame.iat[row, col] = value
    return frame


def _read_legacy_excel(path: Path):
    """Read INEI HTML or SYLK Excel exports, preserving heading rows."""
    import re
    import pandas as pd
    text = path.read_bytes().decode("cp1252")
    if text.startswith("ID;"):
        return _read_sylk(text)
    if re.search(r"(?:Microsoft OLE DB|ADODB|Active Server Pages).*error", text, re.I | re.S):
        raise ValueError("INEI returned an error page instead of a census table")
    # Prevent pandas from promoting the multirow heading to column labels.
    text = re.sub(r"<(/?)thead\b", r"<\1tbody", text, flags=re.I)
    frames = pd.read_html(io.StringIO(text), attrs={"id": "tabDetalle"}, header=None, flavor="lxml")
    if not frames or frames[0].empty:
        raise ValueError("No census table in Excel export")
    return frames[0]


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
