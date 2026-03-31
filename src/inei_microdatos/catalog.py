"""Catalog builder — discovers all surveys, years, periods, modules, and docs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tqdm import tqdm

from inei_microdatos.client import INEIClient, Survey, Period, Module, Doc, PeriodData


# Serialization key for the catalog format
_VERSION = 1
_BUNDLED_CATALOG = Path(__file__).parent / "data" / "catalog.json"


def build_catalog(
    client: Optional[INEIClient] = None,
    surveys: Optional[list[str]] = None,
    years: Optional[tuple[int, int]] = None,
    progress: bool = True,
) -> list[dict[str, Any]]:
    """Crawl the INEI portal and build a full catalog.

    Args:
        client: INEIClient instance (created if not provided).
        surveys: Optional list of survey label substrings to filter.
        years: Optional (min_year, max_year) range to filter.
        progress: Show tqdm progress bar.

    Returns:
        List of catalog entries (serializable dicts).
    """
    if client is None:
        client = INEIClient()

    all_surveys = client.get_surveys()

    if surveys:
        surveys_lower = [s.lower() for s in surveys]
        all_surveys = [
            s for s in all_surveys
            if any(q in s.label.lower() for q in surveys_lower)
        ]

    catalog = []
    iter_surveys = tqdm(all_surveys, desc="Surveys", disable=not progress)

    for survey in iter_surveys:
        iter_surveys.set_postfix_str(survey.label[:40])
        entry = {
            "category": survey.category,
            "value": survey.value,
            "label": survey.label,
            "years": {},
        }

        survey_years = client.get_years(survey)

        if years:
            survey_years = [
                y for y in survey_years
                if years[0] <= int(y) <= years[1]
            ]

        for year in survey_years:
            periods = client.get_periods(survey, year)
            year_data = {}

            for period in periods:
                modules = client.get_modules(survey, year, period)
                docs = client.get_docs(survey, year, period)

                year_data[period.label] = {
                    "period_value": period.value,
                    "modules": [_module_to_dict(m) for m in modules],
                    "docs": [_doc_to_dict(d) for d in docs],
                }

            entry["years"][year] = year_data

        catalog.append(entry)

    return _dedup_catalog(catalog)


# ENAHO methodology boundary: "Anterior" = pre-2004, "Actualizada" = 2004+
_METHODOLOGY_BOUNDARY = 2004


def _dedup_catalog(catalog: list[dict]) -> list[dict]:
    """Remove duplicate entries that share the same value string across categories.

    When the same survey appears in both ENAHO Anterior and ENAHO Actualizada,
    the server returns identical data. We split by methodology boundary:
    Anterior keeps years < 2004, Actualizada keeps years >= 2004.
    """
    seen_values = {}  # value -> index of first occurrence
    to_split = []  # pairs of (first_idx, second_idx)

    for i, entry in enumerate(catalog):
        val = entry["value"]
        if val in seen_values:
            first_idx = seen_values[val]
            first = catalog[first_idx]
            if set(first["years"].keys()) == set(entry["years"].keys()):
                to_split.append((first_idx, i))
        else:
            seen_values[val] = i

    # Split years between the pairs, then drop entries left with no years
    for first_idx, second_idx in to_split:
        _split_by_methodology(catalog[first_idx], catalog[second_idx])

    return [e for e in catalog if e.get("years")]


def _split_by_methodology(anterior: dict, actualizada: dict) -> None:
    """Split years between Anterior (pre-boundary) and Actualizada (boundary+).

    Mutates both entries in place.
    """
    # Figure out which is which
    if "Anterior" in anterior["category"]:
        old, new = anterior, actualizada
    elif "Anterior" in actualizada["category"]:
        old, new = actualizada, anterior
    else:
        return  # can't determine roles, leave both intact

    all_years = dict(old["years"])  # they're identical, pick either

    old["years"] = {y: v for y, v in all_years.items() if int(y) < _METHODOLOGY_BOUNDARY}
    new["years"] = {y: v for y, v in all_years.items() if int(y) >= _METHODOLOGY_BOUNDARY}


def save_catalog(catalog: list[dict], path: str | Path) -> None:
    """Save catalog to a JSON file with timestamp."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "version": _VERSION,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "catalog": catalog,
        }, f, ensure_ascii=False, indent=2)


def load_catalog(path: Optional[str | Path] = None) -> list[dict]:
    """Load catalog from a JSON file.

    If path is None or doesn't exist, falls back to the bundled catalog
    shipped with the package.
    """
    if path is not None:
        path = Path(path)
        if path.exists():
            return _read_catalog_file(path)

    # Fall back to bundled
    if _BUNDLED_CATALOG.exists():
        return _read_catalog_file(_BUNDLED_CATALOG)

    raise FileNotFoundError(
        "No catalog found. Run 'inei-microdatos crawl' to build one, "
        "or reinstall the package to restore the bundled catalog."
    )


def catalog_age(path: Optional[str | Path] = None) -> Optional[str]:
    """Return the crawl timestamp of a catalog, or None if unknown."""
    if path is not None:
        p = Path(path)
        if p.exists():
            return _read_timestamp(p)
    # Fall back to bundled
    if _BUNDLED_CATALOG.exists():
        return _read_timestamp(_BUNDLED_CATALOG)
    return None


def _read_timestamp(path: Path) -> Optional[str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("crawled_at")
    return None


def _read_catalog_file(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data  # legacy format (raw list)
    return data["catalog"]


def catalog_stats(catalog: list[dict]) -> dict[str, int]:
    """Return summary statistics for a catalog."""
    n_surveys = len(catalog)
    n_years = sum(len(e["years"]) for e in catalog)
    n_modules = 0
    n_docs = 0
    n_downloadable = 0
    for entry in catalog:
        for year_data in entry["years"].values():
            for period_data in year_data.values():
                mods = period_data["modules"]
                n_modules += len(mods)
                n_docs += len(period_data["docs"])
                n_downloadable += sum(
                    1 for m in mods
                    if m.get("csv_code") or m.get("stata_code") or m.get("spss_code")
                )
    return {
        "surveys": n_surveys,
        "survey_years": n_years,
        "modules": n_modules,
        "docs": n_docs,
        "downloadable_modules": n_downloadable,
    }


def filter_catalog(
    catalog: list[dict],
    survey: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    period: Optional[str] = None,
) -> list[dict]:
    """Filter catalog entries by survey name (or alias), year range, and/or period."""
    from inei_microdatos.aliases import resolve_alias

    result = []
    if survey:
        survey = resolve_alias(survey)
    sq = survey.lower() if survey else None

    for entry in catalog:
        if sq and sq not in entry["label"].lower():
            continue

        filtered_years = {}
        for yr, year_data in entry["years"].items():
            yr_int = int(yr)
            if year_min and yr_int < year_min:
                continue
            if year_max and yr_int > year_max:
                continue

            if period:
                pl = period.lower()
                filtered_periods = {
                    k: v for k, v in year_data.items()
                    if pl in k.lower()
                }
            else:
                filtered_periods = year_data

            if filtered_periods:
                filtered_years[yr] = filtered_periods

        if filtered_years:
            result.append({**entry, "years": filtered_years})

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _module_to_dict(m: Module) -> dict:
    return {
        "survey_code": m.survey_code,
        "module_code": m.module_code,
        "module_name": m.name,
        "csv_code": m.csv_code,
        "stata_code": m.stata_code,
        "spss_code": m.spss_code,
    }


def _doc_to_dict(d: Doc) -> dict:
    return {
        "doc_code": d.code,
        "doc_name": d.name,
        "zip_path": d.zip_path,
        "ficha_params": d.ficha_params,
    }
