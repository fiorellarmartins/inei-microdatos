"""Download microdata and documentation files from INEI."""

from __future__ import annotations

import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

from inei_microdatos.client import DOWNLOAD_BASE, BASE_URL

_TIMEOUT = 120
_CHUNK = 8192
_MAX_RETRIES = 3

# Folder layout presets.
# Placeholders: {survey}, {year}, {period}, {code}, {module_name}, {format}
LAYOUTS = {
    "default":  "{survey}/{year}/{period}/{code}.zip",
    "flat":     "{survey}/{code}.zip",
    "by-year":  "{survey}/{year}/{code}.zip",
    "by-format":"{format}/{survey}/{year}/{code}.zip",
}


def download_modules(
    catalog: list[dict],
    dest: str | Path,
    fmt: str = "CSV",
    fallback: bool = True,
    layout: str = "default",
    workers: int = 4,
    progress: bool = True,
    dry_run: bool = False,
) -> dict[str, int]:
    """Download microdata ZIPs or aggregate XLS/XLSX tables from a catalog.

    Args:
        catalog: Catalog entries (from build_catalog or load_catalog).
        dest: Destination directory.
        fmt: Format — "CSV", "STATA", "SPSS", "XLSX", or "XLS".
        fallback: If True, fall back to another format when preferred isn't available.
        layout: Folder layout — "default", "flat", "by-year", "by-format",
            or a custom template with {survey}, {year}, {period}, {code},
            {module_name}, {format} placeholders.
        workers: Number of parallel download threads.
        progress: Show progress bar.
        dry_run: If True, print what would be downloaded without downloading.

    Returns:
        Dict with counts: ok, skipped, failed, bad_zip (or files/would_skip for dry_run).
    """
    fmt = fmt.upper()
    if fmt not in ("CSV", "STATA", "SPSS", "XLSX", "XLS"):
        raise ValueError(f"Invalid format: {fmt}. Must be CSV, STATA, SPSS, XLSX, or XLS.")

    template = LAYOUTS.get(layout, layout)
    tasks = _collect_module_tasks(catalog, dest, fmt, fallback, template)
    if dry_run:
        return _dry_run_report(tasks)
    return _run_downloads(tasks, workers, progress, desc=f"Downloading {fmt}")


def download_docs(
    catalog: list[dict],
    dest: str | Path,
    layout: str = "default",
    workers: int = 4,
    progress: bool = True,
    dry_run: bool = False,
) -> dict[str, int]:
    """Download documentation ZIP files for all docs in a catalog.

    Returns:
        Dict with counts: ok, skipped, failed, bad_zip (or files/would_skip for dry_run).
    """
    template = LAYOUTS.get(layout, layout)
    tasks = _collect_doc_tasks(catalog, dest, template)
    if dry_run:
        return _dry_run_report(tasks)
    return _run_downloads(tasks, workers, progress, desc="Downloading docs")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_FORMAT_KEYS = {"CSV": "csv_code", "STATA": "stata_code", "SPSS": "spss_code"}
_FORMATS = ("CSV", "STATA", "SPSS", "XLSX", "XLS")


def module_download(mod: dict, fmt: str, fallback: bool = True):
    """Return (URL, code, actual format, extension), or None if unavailable."""
    fmt = fmt.upper()
    if fmt not in _FORMATS:
        raise ValueError(f"Invalid format: {fmt}")
    order = {
        "CSV": ("CSV", "STATA", "SPSS", "XLSX", "XLS"),
        "STATA": ("STATA", "CSV", "SPSS", "XLSX", "XLS"),
        "SPSS": ("SPSS", "STATA", "CSV", "XLSX", "XLS"),
        "XLSX": ("XLSX", "XLS", "CSV", "STATA", "SPSS"),
        "XLS": ("XLS", "XLSX", "CSV", "STATA", "SPSS"),
    }
    formats = order[fmt] if fallback else [fmt]
    for actual_fmt in formats:
        if actual_fmt in ("XLSX", "XLS"):
            url = mod.get(actual_fmt.lower() + "_url")
            if url:
                return url, mod["module_code"], actual_fmt, "." + actual_fmt.lower()
        else:
            code = mod.get(_FORMAT_KEYS[actual_fmt])
            if code:
                return f"{DOWNLOAD_BASE}{actual_fmt}/{code}.zip", code, actual_fmt, ".zip"
    return None


def _collect_module_tasks(
    catalog: list[dict], dest: str | Path, fmt: str, fallback: bool,
    template: str,
) -> list[tuple[str, Path]]:
    dest = Path(dest)
    tasks = []
    for entry in catalog:
        for year, year_data in entry["years"].items():
            for period_label, period_data in year_data.items():
                for mod in period_data["modules"]:
                    selected = module_download(mod, fmt, fallback)
                    if not selected:
                        continue
                    url, code, actual_fmt, extension = selected
                    rel = template.format(
                        survey=_safe_dirname(entry["label"]),
                        year=year,
                        period=_safe_dirname(period_label),
                        code=code,
                        module_name=_safe_dirname(mod.get("module_name", code)),
                        format=actual_fmt,
                    )
                    if extension in (".xlsx", ".xls"):
                        rel = str(Path(rel).with_suffix(extension))
                    tasks.append((url, dest / rel))
    return tasks


def _collect_doc_tasks(
    catalog: list[dict], dest: str | Path, template: str,
) -> list[tuple[str, Path]]:
    dest = Path(dest)
    tasks = []
    for entry in catalog:
        for year, year_data in entry["years"].items():
            for period_label, period_data in year_data.items():
                for doc in period_data.get("docs", []):
                    zp = doc.get("zip_path")
                    if not zp:
                        continue
                    url = f"{DOWNLOAD_BASE}DocumentosZIP/{zp}"
                    filename = zp.split("/")[-1]
                    # Use template for docs, replacing {code} with filename
                    rel = template.format(
                        survey=_safe_dirname(entry["label"]),
                        year=year,
                        period=_safe_dirname(period_label),
                        code="docs/" + Path(filename).stem,
                        module_name="docs",
                        format="docs",
                    )
                    # Keep the original extension
                    rel = str(Path(rel).with_suffix(Path(filename).suffix))
                    tasks.append((url, dest / rel))
    return tasks


def _run_downloads(
    tasks: list[tuple[str, Path]],
    workers: int,
    progress: bool,
    desc: str,
) -> dict[str, int]:
    stats = {"ok": 0, "skipped": 0, "failed": 0, "bad_zip": 0}

    if not tasks:
        return stats

    bar = tqdm(total=len(tasks), desc=desc, disable=not progress)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_one, url, path): (url, path) for url, path in tasks}
        for future in as_completed(futures):
            result = future.result()
            stats[result] += 1
            bar.update(1)
            bar.set_postfix(ok=stats["ok"], skip=stats["skipped"], fail=stats["failed"])

    bar.close()
    return stats


def _valid_download(path: Path) -> bool:
    if path.suffix.lower() == ".xls":
        from inei_microdatos.reader import _read_legacy_excel
        try:
            return not _read_legacy_excel(path).empty
        except (ValueError, OSError):
            return False
    if not zipfile.is_zipfile(path):
        return False
    if path.suffix.lower() == ".xlsx":
        with zipfile.ZipFile(path) as workbook:
            return {"[Content_Types].xml", "xl/workbook.xml"}.issubset(workbook.namelist())
    return True


def _download_one(url: str, dest: Path) -> str:
    if dest.exists():
        if dest.stat().st_size > 0 and _valid_download(dest):
            return "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.get(url, timeout=_TIMEOUT, stream=True)
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(_CHUNK):
                    f.write(chunk)
            if not _valid_download(dest):
                dest.unlink(missing_ok=True)
                return "bad_zip"
            return "ok"
        except Exception:
            if dest.exists():
                dest.unlink(missing_ok=True)
            if attempt == _MAX_RETRIES - 1:
                return "failed"

    return "failed"


def _dry_run_report(tasks: list) -> dict:
    """Print what would be downloaded and return summary stats."""
    would_download = 0
    would_skip = 0
    for url, path in tasks:
        if path.exists() and path.stat().st_size > 0 and _valid_download(path):
            would_skip += 1
        else:
            would_download += 1
            print(f"  {url}")
            print(f"    -> {path}")

    print(f"\n  {would_download} files to download, {would_skip} already exist")
    return {"files": would_download, "would_skip": would_skip}


def _safe_dirname(s: str) -> str:
    """Convert a label to a filesystem-safe directory name."""
    s = s.replace("/", "-").replace("\\", "-")
    # Remove chars that cause issues on Windows/macOS
    for ch in '<>:"|?*':
        s = s.replace(ch, "")
    return s.strip().rstrip(".")[:120]
