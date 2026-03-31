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
    """Download microdata ZIP files for all modules in a catalog.

    Args:
        catalog: Catalog entries (from build_catalog or load_catalog).
        dest: Destination directory.
        fmt: Format — "CSV", "STATA", or "SPSS".
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
    if fmt not in ("CSV", "STATA", "SPSS"):
        raise ValueError(f"Invalid format: {fmt}. Must be CSV, STATA, or SPSS.")

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
_FALLBACK_ORDER = {"CSV": ["csv_code", "stata_code", "spss_code"],
                   "STATA": ["stata_code", "csv_code", "spss_code"],
                   "SPSS": ["spss_code", "stata_code", "csv_code"]}
_KEY_TO_FMT = {"csv_code": "CSV", "stata_code": "STATA", "spss_code": "SPSS"}


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
                    keys = _FALLBACK_ORDER[fmt] if fallback else [_FORMAT_KEYS[fmt]]
                    code = None
                    actual_fmt = fmt
                    for key in keys:
                        code = mod.get(key)
                        if code:
                            actual_fmt = _KEY_TO_FMT[key]
                            break
                    if not code:
                        continue
                    url = f"{DOWNLOAD_BASE}{actual_fmt}/{code}.zip"
                    rel = template.format(
                        survey=_safe_dirname(entry["label"]),
                        year=year,
                        period=_safe_dirname(period_label),
                        code=code,
                        module_name=_safe_dirname(mod.get("module_name", code)),
                        format=actual_fmt,
                    )
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


def _download_one(url: str, dest: Path) -> str:
    if dest.exists():
        if dest.stat().st_size > 0 and zipfile.is_zipfile(dest):
            return "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.get(url, timeout=_TIMEOUT, stream=True)
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(_CHUNK):
                    f.write(chunk)
            if not zipfile.is_zipfile(dest):
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
    import zipfile as _zf

    would_download = 0
    would_skip = 0
    for url, path in tasks:
        if path.exists() and path.stat().st_size > 0 and _zf.is_zipfile(path):
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
