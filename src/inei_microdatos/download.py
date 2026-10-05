"""Download microdata and documentation files from INEI."""

from __future__ import annotations

import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from threading import Lock, RLock

import requests
from tqdm import tqdm

from inei_microdatos.client import DOWNLOAD_BASE, BASE_URL

_TIMEOUT = 120
_CHUNK = 8192
_MAX_RETRIES = 3
_PATH_LOCKS = {}
_PATH_LOCKS_GUARD = Lock()

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
    ubigeo: Optional[str] = None,
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
        ubigeo: INEI code: 2 digits (department), 4 (province), 6 (district).

    Returns:
        Dict with counts: ok, skipped, failed, bad_zip (or files/would_skip for dry_run).
        Geographic downloads may add unavailable (no supported tables), empty
        (no matching survey observations), or partial (unresolved survey records/tables).
    """
    fmt = fmt.upper()
    if fmt not in ("CSV", "STATA", "SPSS", "XLSX", "XLS"):
        raise ValueError(f"Invalid format: {fmt}. Must be CSV, STATA, SPSS, XLSX, or XLS.")

    template = LAYOUTS.get(layout, layout)
    if ubigeo is not None:
        from inei_microdatos.survey_geography import select_geography
        catalog = select_geography(catalog, ubigeo)
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
    """Return (URL or query descriptor, code, format, extension), or None."""
    fmt = fmt.upper()
    if fmt not in _FORMATS:
        raise ValueError(f"Invalid format: {fmt}")
    if mod.get("survey_geography_query"):
        if fmt != "CSV" and not fallback:
            raise ValueError("Derived survey subsets use CSV; choose CSV or enable format fallback")
        code = (mod.get("csv_code") or mod["module_code"]) + "-ubigeo-" + mod["geography"]["code"]
        return mod["survey_geography_query"], code, "CSV", ".zip"
    order = {
        "CSV": ("CSV", "STATA", "SPSS", "XLSX", "XLS"),
        "STATA": ("STATA", "CSV", "SPSS", "XLSX", "XLS"),
        "SPSS": ("SPSS", "STATA", "CSV", "XLSX", "XLS"),
        "XLSX": ("XLSX", "XLS", "CSV", "STATA", "SPSS"),
        "XLS": ("XLS", "XLSX", "CSV", "STATA", "SPSS"),
    }
    formats = order[fmt] if fallback else [fmt]
    code = mod.get("module_code", "")
    if mod.get("geography"):
        code += "-ubigeo-" + mod["geography"]["code"]
    for actual_fmt in formats:
        if actual_fmt in ("XLSX", "XLS"):
            if actual_fmt == "XLSX" and mod.get("geography_query"):
                return mod["geography_query"], code, "XLSX", ".xlsx"
            if actual_fmt == "XLS" and mod.get("redatam_query"):
                return mod["redatam_query"], code, "XLS", ".xls"
            url = mod.get(actual_fmt.lower() + "_url")
            if url:
                return url, code, actual_fmt, "." + actual_fmt.lower()
        else:
            archive_code = mod.get(_FORMAT_KEYS[actual_fmt])
            if archive_code:
                return f"{DOWNLOAD_BASE}{actual_fmt}/{archive_code}.zip", archive_code, actual_fmt, ".zip"
    return None


def _collect_module_tasks(
    catalog: list[dict], dest: str | Path, fmt: str, fallback: bool,
    template: str,
) -> list[tuple[str | dict, Path]]:
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
                    if mod.get("geography"):
                        # Isolate selections even when a custom layout omits {code}.
                        rel_path = Path(rel)
                        rel = str(rel_path.parent / ("ubigeo-" + mod["geography"]["code"]) / rel_path.name)
                        if isinstance(url, dict) and url.get("kind") == "census_geography":
                            url = dict(url, source_path=str(dest / rel_path.parent / (mod["module_code"] + ".xlsx")))
                        elif isinstance(url, dict) and url.get("kind") == "survey_geography":
                            url = dict(url, source_path=str(dest / rel_path.parent / ".geography-sources" /
                                                           "CSV" / (url["module_code"] + ".zip")))
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
    tasks: list[tuple[str | dict, Path]],
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
            if result not in stats:
                stats[result] = 0
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


def _download_one(url: str | dict, dest: Path) -> str:
    # Multiple ENDES modules share parent archives. Never read a partially written cache.
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.setdefault(str(dest.resolve()), RLock())
    with lock:
        return _download_one_locked(url, dest)


def _download_one_locked(url: str | dict, dest: Path) -> str:
    from inei_microdatos.geography import GeographyUnavailable
    if isinstance(url, dict) and url.get("kind") == "geography_unavailable":
        return "unavailable"
    if dest.exists():
        if dest.stat().st_size > 0 and _valid_download(dest):
            if not isinstance(url, dict) or url.get("kind") != "survey_geography":
                return "skipped"
            from inei_microdatos.survey_geography import matching_subset
            if matching_subset(dest, url):
                return "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(_MAX_RETRIES):
        try:
            outcome = "ok"
            if isinstance(url, dict) and url.get("kind") == "survey_geography":
                from inei_microdatos.survey_geography import subset_survey_archive
                raw = Path(url.get("source_path", dest.parent / ".geography-sources" / "CSV" / (url["module_code"] + ".zip")))
                if _download_one(url["url"], raw) not in ("ok", "skipped"):
                    raise OSError("Could not download source survey archive")
                outcome = subset_survey_archive(raw, dest, url)
            elif isinstance(url, dict) and url.get("kind") == "census_geography":
                from inei_microdatos.geography import subset_workbook
                raw = Path(url.get("source_path", dest.parent / (url["module_code"] + ".xlsx")))
                if _download_one(url["url"], raw) not in ("ok", "skipped"):
                    raise OSError("Could not download source census workbook")
                subset_workbook(raw, dest, url["geography"])
            elif isinstance(url, dict):
                from inei_microdatos.redatam import export_excel
                dest.write_bytes(export_excel(url))
            else:
                r = requests.get(url, timeout=_TIMEOUT, stream=True)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(_CHUNK):
                        f.write(chunk)
            if not _valid_download(dest):
                dest.unlink(missing_ok=True)
                return "bad_zip"
            return outcome
        except GeographyUnavailable:
            dest.unlink(missing_ok=True)
            return "unavailable"
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
    unavailable = 0
    for url, path in tasks:
        if isinstance(url, dict) and url.get("kind") == "geography_unavailable":
            unavailable += 1
            print(f"  unavailable: {path.name} ({url['reason']})")
            continue
        cached = path.exists() and path.stat().st_size > 0 and _valid_download(path)
        if cached and isinstance(url, dict) and url.get("kind") == "survey_geography":
            from inei_microdatos.survey_geography import matching_subset
            cached = matching_subset(path, url)
        if cached:
            would_skip += 1
        else:
            would_download += 1
            if isinstance(url, dict) and url.get("kind") == "survey_geography":
                print(f"  {url['url']} -> derived CSV subset, ubigeo {url['code']}")
                parents = sorted({t["parent_code"] for t in url["rule"]["tables"] if t.get("parent_code")})
                if parents:
                    print(f"    Geographic dependencies (reused when cached): {', '.join(parents)}")
            else:
                print(f"  {url}")
            print(f"    -> {path}")

    print(f"\n  {would_download} files to download, {would_skip} already exist")
    result = {"files": would_download, "would_skip": would_skip}
    if unavailable:
        result["unavailable"] = unavailable
    return result


def _safe_dirname(s: str) -> str:
    """Convert a label to a filesystem-safe directory name."""
    s = s.replace("/", "-").replace("\\", "-")
    # Remove chars that cause issues on Windows/macOS
    for ch in '<>:"|?*':
        s = s.replace(ch, "")
    return s.strip().rstrip(".")[:120]
