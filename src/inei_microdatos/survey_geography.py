"""Verified survey geography, offline capabilities, and derived CSV subsets."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import io
import hashlib
import json
from pathlib import Path
import zipfile

from inei_microdatos.census import CENSUS_VALUE
from inei_microdatos.client import DOWNLOAD_BASE
from inei_microdatos.geography import GeographyUnavailable, select_census_geography, validate_ubigeo

LEVELS = {2: "department", 4: "province", 6: "district"}
MANIFEST = "geography.json"


def rule_fingerprint(rule):
    return hashlib.sha256(json.dumps(rule, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def matching_subset(path, query):
    try:
        with zipfile.ZipFile(path) as archive:
            report = json.loads(archive.read(MANIFEST))
        return report["ubigeo"] == query["code"] and report.get("rule_fingerprint") == rule_fingerprint(query["rule"])
    except (KeyError, ValueError, OSError, zipfile.BadZipFile):
        return False


@lru_cache(maxsize=1)
def _registry():
    data = json.loads((Path(__file__).parent / "data/survey_geography.json").read_text(encoding="utf-8"))
    return {(r["survey_value"], r["year"], r["period"], r["archive_code"]): r for r in data["records"]}


def _rule(entry, year, period, mod):
    return _registry().get((entry["value"], str(year), period, mod.get("csv_code")))


def geography_capabilities(catalog: list[dict]) -> list[dict]:
    """Report verified levels per module/table without downloading or guessing."""
    result = []
    for entry in catalog:
        for year, periods in entry["years"].items():
            for period, data in periods.items():
                for mod in data["modules"]:
                    info = dict(survey=entry["label"], year=year, period=period,
                                module_code=mod["module_code"], module_name=mod["module_name"])
                    if entry["value"] == CENSUS_VALUE:
                        info.update(status="table_dependent", levels=list(LEVELS.values()), tables=[],
                                    reason="Census availability depends on the requested area and table")
                    else:
                        rule = _rule(entry, year, period, mod)
                        if rule:
                            tables = [dict(table=Path(t["path"]).name, method=t["method"], levels=t["levels"],
                                           reason=t.get("reason")) for t in rule["tables"]]
                            info.update(status="verified", levels=[v for v in LEVELS.values()
                                        if any(v in t["levels"] for t in tables)], tables=tables,
                                        meaning=rule["meaning"], sources=rule["sources"], output_format="CSV")
                        else:
                            info.update(status="not_verified", levels=[], tables=[],
                                        reason="No reviewed adapter for this survey/year/period/module")
                    result.append(info)
    return result


def annotate_catalog(catalog: list[dict]) -> list[dict]:
    """Attach capability summaries to freshly loaded/built catalog modules."""
    capabilities = iter(geography_capabilities(catalog))
    for entry in catalog:
        for periods in entry["years"].values():
            for data in periods.values():
                for mod in data["modules"]:
                    cap = next(capabilities)
                    mod["geography_support"] = {k: v for k, v in cap.items()
                                                 if k not in {"survey", "year", "period", "module_code", "module_name"}}
    return catalog


def select_geography(catalog: list[dict], ubigeo: str) -> list[dict]:
    """Apply the common selection contract to censuses and verified surveys."""
    code = validate_ubigeo(ubigeo)
    result = []
    for original in catalog:
        if original["value"] == CENSUS_VALUE:
            result.extend(select_census_geography([original], code))
            continue
        entry = deepcopy(original)
        for year, periods in entry["years"].items():
            for period, data in periods.items():
                for mod in data["modules"]:
                    if mod.get("geography"):
                        raise ValueError("Select geography from the original national catalog")
                    rule = _rule(entry, year, period, mod)
                    mod["geography"] = {"code": code, "year": year}
                    if rule is None or not any(LEVELS[len(code)] in t["levels"] for t in rule["tables"]):
                        mod["survey_geography_query"] = {"kind": "geography_unavailable", "code": code,
                            "reason": "No verified support for this geographic level; inspect geography_capabilities()"}
                        continue
                    mod["survey_geography_query"] = {
                        "kind": "survey_geography", "code": code, "rule": deepcopy(rule),
                        "url": DOWNLOAD_BASE + "CSV/" + rule["archive_code"] + ".zip",
                        "module_code": rule["archive_code"],
                    }
        result.append(entry)
    return result


def _codes(series, width):
    """Normalize numeric codes only; never truncate or interpret labels as IDs."""
    values = series.astype("string").str.strip().str.replace(r"\.0+$", "", regex=True)
    valid = values.str.fullmatch(r"[0-9]{1," + str(width) + "}", na=False)
    result = values.where(valid).str.zfill(width)
    for start in range(0, width, 2):
        result = result.where(result.str[start:start + 2] != "00")
    return result


def _row_codes(frame, spec, width=6):
    for col in spec["columns"]:
        if col not in frame:
            raise ValueError(f"Official schema changed: missing geographic column {col}")
    if spec["method"] == "ubigeo":
        raw = frame[spec["columns"][0]].astype("string").str.strip().str.replace(r"\.0+$", "", regex=True)
        raw = raw.where(raw.str.fullmatch(r"[0-9]{1,6}", na=False)).str.zfill(6)
        result = _codes(raw.str[:width], width)
    elif spec["method"] == "department":
        result = _codes(frame[spec["columns"][0]], 2)
    elif spec["method"] == "components":
        parts = [_codes(frame[col], 2) for col in spec["columns"][:width // 2]]
        result = parts[0]
        for part in parts[1:]:
            result = result + part
    else:
        raise ValueError("Expected a direct geographic field")
    return result.where(result.str[:2].between("01", "25"))


def _chunks(archive, spec, usecols=None):
    import pandas as pd
    with archive.open(spec["path"]) as stream:
        yield from pd.read_csv(stream, encoding=spec["encoding"], sep=spec["delimiter"],
                               dtype=str, keep_default_na=False, chunksize=25000, usecols=usecols)


def _parent_mapping(rule, spec, source_dir, width):
    import pandas as pd
    from inei_microdatos.download import _download_one
    key = (rule["survey_value"], rule["year"], rule["period"], spec["parent_code"])
    parent = _registry().get(key)
    if parent is None:
        raise ValueError("Unverified geographic dependency")
    matches = [t for t in parent["tables"] if Path(t["path"]).name == spec["parent_table"]]
    if len(matches) != 1 or matches[0]["method"] != "ubigeo":
        raise ValueError("Ambiguous geographic dependency")
    parent_spec = matches[0]
    source = source_dir / (spec["parent_code"] + ".zip")
    url = DOWNLOAD_BASE + "CSV/" + spec["parent_code"] + ".zip"
    if _download_one(url, source) not in {"ok", "skipped"}:
        raise OSError(f"Could not download geographic dependency {spec['parent_code']}")
    keys, codes = [], []
    with zipfile.ZipFile(source) as archive:
        for frame in _chunks(archive, parent_spec, [spec["parent_key"]] + parent_spec["columns"]):
            keys.extend(frame[spec["parent_key"]].str.strip())
            codes.extend(_row_codes(frame, parent_spec, width))
    mapping = pd.Series(codes, index=keys, dtype="string")
    if mapping.index.has_duplicates or "" in mapping.index:
        raise ValueError("Geographic parent keys must be unique and non-empty")
    return mapping


def subset_survey_archive(source: Path, dest: Path, query: dict) -> str:
    """Stream a derived ZIP, retaining original values and reporting omissions."""
    code, rule = query["code"], query["rule"]
    level = LEVELS[len(code)]
    report = {"version": 1, "ubigeo": code, "survey": rule["survey_value"], "year": rule["year"],
              "period": rule["period"], "meaning": rule["meaning"], "source_url": query["url"],
              "sources": rule["sources"], "tables": [], "omitted_tables": []}
    report["rule_fingerprint"] = rule_fingerprint(rule)
    mappings, total_selected = {}, 0
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as output:
        known = {t["path"] for t in rule["tables"]}
        actual = {n for n in archive.namelist() if n.lower().endswith(".csv")}
        if actual != known:
            raise ValueError("Official archive table list changed; geographic adapter needs review")
        for spec in rule["tables"]:
            filename = Path(spec["path"]).name
            if level not in spec["levels"]:
                report["omitted_tables"].append({"table": filename, "reason": spec.get("reason", "Unsupported geographic level")})
                continue
            mapping = None
            if spec["method"] == "join":
                dep = (spec["parent_code"], spec["parent_table"], spec["parent_key"])
                if dep not in mappings:
                    mappings[dep] = _parent_mapping(rule, spec, source.parent, len(code))
                mapping = mappings[dep]
            info = {"file": filename, "method": spec["method"], "rows": 0, "source_rows": 0,
                    "unlocated_rows": 0, "text_columns": spec["text_columns"]}
            if mapping is not None:
                info["dependency"] = {k: spec[k] for k in ("parent_code", "parent_table", "parent_key")}
            with output.open(filename, "w", force_zip64=True) as binary:
                with io.TextIOWrapper(binary, encoding="utf-8", newline="") as stream:
                    first = True
                    for frame in _chunks(archive, spec):
                        if mapping is None:
                            geographic = _row_codes(frame, spec, len(code))
                        else:
                            geographic = frame[spec["columns"][0]].str.strip().map(mapping)
                        mask = geographic.astype("string").str.startswith(code, na=False)
                        selected = frame.loc[mask]
                        selected.to_csv(stream, index=False, header=first)
                        first = False
                        info["source_rows"] += len(frame)
                        info["rows"] += len(selected)
                        info["unlocated_rows"] += int(geographic.isna().sum())
            total_selected += info["rows"]
            report["tables"].append(info)
        if not report["tables"]:
            raise GeographyUnavailable("No tables support the requested geographic level")
        report["status"] = ("partial" if any(t["unlocated_rows"] for t in report["tables"])
                            or any(t["reason"] != "Reference table" for t in report["omitted_tables"])
                            else "ok" if total_selected else "empty")
        output.writestr(MANIFEST, json.dumps(report, ensure_ascii=False, indent=2))
    return report["status"]
