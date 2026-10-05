import io
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import zipfile

import pandas as pd
import pytest
from click.testing import CliRunner

from inei_microdatos import geography_capabilities, select_geography
from inei_microdatos.catalog import filter_catalog, load_catalog
from inei_microdatos.cli import cli
from inei_microdatos.download import _collect_module_tasks, _download_one, download_modules, module_download
from inei_microdatos.geography import GeographyUnavailable
from inei_microdatos.reader import read_catalog_entry, read_module
from inei_microdatos.survey_geography import _codes, _registry, subset_survey_archive


def write_zip(path, tables):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, text in tables.items():
            z.writestr(name, text)


@pytest.fixture
def fixture_registry(monkeypatch):
    direct = dict(path="households.csv", method="ubigeo", columns=["UBIGEO"],
                  levels=["department", "province", "district"], encoding="utf-8-sig", delimiter=",",
                  text_columns=["UBIGEO", "HHID"])
    components = dict(direct, path="units.csv", method="components", columns=["CCDD", "CCPP", "CCDI"],
                      delimiter=";", text_columns=["CCDD", "CCPP", "CCDI"])
    child = dict(direct, path="children.csv", method="join", columns=["HHID"], parent_code="BASE",
                 parent_table="households.csv", parent_key="HHID", text_columns=["HHID"])
    department = dict(direct, path="departments.csv", method="department", columns=["CCDD"],
                      levels=["department"], text_columns=["CCDD"])
    rules = {}
    for code, tables in (("BASE", [direct]), ("CHILD", [child]), ("PARTS", [components]), ("DEP", [department])):
        rules[("Survey", "2024", "Annual", code)] = dict(survey_value="Survey", year="2024", period="Annual",
            archive_code=code, meaning="household_location", sources=["https://example.org/dictionary"], tables=tables)
    monkeypatch.setattr("inei_microdatos.survey_geography._registry", lambda: rules)
    return rules


def catalog(code="BASE", year="2024"):
    return [{"value": "Survey", "label": "Survey", "category": "Standalone", "years": {
        year: {"Annual": {"docs": [], "modules": [{"module_code": code, "module_name": code,
                                                    "csv_code": code, "stata_code": code}]}}}}]


def query(rules, code="BASE", ubigeo="010101"):
    return {"kind": "survey_geography", "code": ubigeo, "module_code": code,
            "url": "https://example.org/" + code + ".zip", "rule": rules[("Survey", "2024", "Annual", code)]}


@pytest.mark.parametrize("code,expected", [("01", ["0001", "0002"]), ("0101", ["0001"]), ("010101", ["0001"])])
def test_direct_prefixes_preserve_values_and_leading_zeros(fixture_registry, tmp_path, code, expected):
    raw, dest = tmp_path / "BASE.zip", tmp_path / "subset.zip"
    write_zip(raw, {"households.csv": "HHID,UBIGEO,weight,value\n0001,010101,1.25,20\n0002,010201,2.75,30\n0003,150101,9.5,40\n"})
    before = raw.read_bytes()
    assert subset_survey_archive(raw, dest, query(fixture_registry, ubigeo=code)) == "ok"
    f = read_module(dest)["households"]
    assert f.HHID.tolist() == expected
    assert f.UBIGEO.iloc[0] == "010101"
    assert f.weight.iloc[0] == 1.25
    assert raw.read_bytes() == before
    assert f.attrs["ubigeo"] == code


def test_numeric_normalization_never_truncates_or_matches_invalid_codes():
    codes = _codes(pd.Series([10101, "010101.0", "010101", "1501019", "Lima", "", None, "000101"]), 6)
    assert codes.iloc[:3].tolist() == ["010101"] * 3
    assert codes.iloc[3:].isna().all()


def test_component_csv_separator_and_empty_selection(fixture_registry, tmp_path):
    raw, dest = tmp_path / "PARTS.zip", tmp_path / "subset.zip"
    write_zip(raw, {"units.csv": "CCDD;CCPP;CCDI;weight\n1;1;1;5.25\n15;1;1;2.5\n"})
    assert subset_survey_archive(raw, dest, query(fixture_registry, "PARTS")) == "ok"
    assert read_module(dest)["units"].weight.tolist() == [5.25]
    assert subset_survey_archive(raw, dest, query(fixture_registry, "PARTS", "020101")) == "empty"
    frame = read_module(dest)["units"]
    assert frame.empty
    assert frame.attrs["geography_report"]["status"] == "empty"
    assert list(frame.columns) == ["CCDD", "CCPP", "CCDI", "weight"]


def test_join_preserves_children_without_row_multiplication_and_reports_orphans(fixture_registry, tmp_path, monkeypatch):
    write_zip(tmp_path / "BASE.zip", {"households.csv": "HHID,UBIGEO\n0001,010101\n0002,150101\n"})
    write_zip(tmp_path / "CHILD.zip", {"children.csv": "HHID,child,weight\n0001,1,1.25\n0001,2,3.25\n0002,1,7\n0099,1,9\n"})
    network = Mock(side_effect=AssertionError("Use cached dependency"))
    monkeypatch.setattr("inei_microdatos.download.requests.get", network)
    dest = tmp_path / "subset.zip"
    assert subset_survey_archive(tmp_path / "CHILD.zip", dest, query(fixture_registry, "CHILD")) == "partial"
    frame = read_module(dest)["children"]
    assert frame.child.tolist() == [1, 2]
    assert frame.weight.tolist() == [1.25, 3.25]
    assert frame.attrs["geographic_rows"]["unlocated_rows"] == 1
    assert frame.attrs["geography_report"]["status"] == "partial"
    network.assert_not_called()


def test_duplicate_parent_keys_fail_closed(fixture_registry, tmp_path):
    write_zip(tmp_path / "BASE.zip", {"households.csv": "HHID,UBIGEO\n0001,010101\n0001,150101\n"})
    write_zip(tmp_path / "CHILD.zip", {"children.csv": "HHID,weight\n0001,1\n"})
    with pytest.raises(ValueError, match="unique"):
        subset_survey_archive(tmp_path / "CHILD.zip", tmp_path / "subset.zip", query(fixture_registry, "CHILD"))


def test_missing_district_does_not_remove_known_department_rows(fixture_registry, tmp_path):
    raw, dest = tmp_path / "PARTS.zip", tmp_path / "subset.zip"
    write_zip(raw, {"units.csv": "CCDD;CCPP;CCDI;weight\n01;01;;5\n01;;;7\n15;01;01;8\n"})
    assert subset_survey_archive(raw, dest, query(fixture_registry, "PARTS", "01")) == "ok"
    assert read_module(dest)["units"].weight.tolist() == [5, 7]
    assert subset_survey_archive(raw, dest, query(fixture_registry, "PARTS", "010101")) == "partial"
    assert read_module(dest)["units"].empty


def test_unsupported_tables_are_reported_never_copied_unfiltered(fixture_registry, tmp_path):
    r = fixture_registry[("Survey", "2024", "Annual", "BASE")]
    r["tables"].append(dict(path="unverified.csv", method="unsupported", levels=[], columns=[],
                            reason="No verified relationship", text_columns=[], encoding="utf-8", delimiter=","))
    raw, dest = tmp_path / "BASE.zip", tmp_path / "subset.zip"
    write_zip(raw, {"households.csv": "HHID,UBIGEO\n0001,010101\n0002,150101\n", "unverified.csv": "sensitive_value\n99\n"})
    assert subset_survey_archive(raw, dest, query(fixture_registry)) == "partial"
    with zipfile.ZipFile(dest) as z:
        assert "unverified.csv" not in z.namelist()
        assert json.loads(z.read("geography.json"))["omitted_tables"][0]["table"] == "unverified.csv"


def test_stale_subset_cache_is_not_reused(fixture_registry, tmp_path):
    raw, dest = tmp_path / "BASE.zip", tmp_path / "subset.zip"
    write_zip(raw, {"households.csv": "HHID,UBIGEO\n0001,010101\n0002,150101\n"})
    first = dict(query(fixture_registry), source_path=str(raw))
    assert _download_one(first, dest) == "ok"
    assert _download_one(first, dest) == "skipped"
    second = dict(query(fixture_registry, ubigeo="150101"), source_path=str(raw))
    assert _download_one(second, dest) == "ok"
    assert read_module(dest)["households"].HHID.tolist() == ["0002"]
    second["rule"]["sources"].append("https://example.org/reviewed-again")
    assert _download_one(second, dest) == "ok"


def test_mixed_catalog_routes_censuses_and_surveys(fixture_registry, monkeypatch):
    census = [{"value": "CPV", "label": "Census", "years": {}}]
    from inei_microdatos.census import CENSUS_VALUE
    census[0]["value"] = CENSUS_VALUE
    route = Mock(return_value=[dict(census[0], selected="01")])
    monkeypatch.setattr("inei_microdatos.survey_geography.select_census_geography", route)
    selected = select_geography(census + catalog(), "01")
    route.assert_called_once_with(census, "01")
    assert selected[0]["selected"] == "01"
    assert selected[1]["years"]["2024"]["Annual"]["modules"][0]["geography"]["code"] == "01"


def test_capabilities_fail_closed_for_other_years_and_finer_levels(fixture_registry, tmp_path, monkeypatch):
    network = Mock(side_effect=AssertionError("Unsupported selections must not download"))
    monkeypatch.setattr("inei_microdatos.download.requests.get", network)
    assert geography_capabilities(catalog("DEP"))[0]["levels"] == ["department"]
    assert geography_capabilities(catalog(year="2023"))[0]["status"] == "not_verified"
    assert download_modules(catalog("DEP"), tmp_path, ubigeo="010101", progress=False)["unavailable"] == 1
    with pytest.raises(GeographyUnavailable):
        read_catalog_entry(catalog("DEP")[0], "2024", dest=tmp_path, ubigeo="010101")
    assert not list(tmp_path.rglob("*.zip"))
    network.assert_not_called()


def test_unregistered_schema_changes_do_not_produce_cached_output(fixture_registry, tmp_path):
    raw = tmp_path / "BASE.zip"
    write_zip(raw, {"households.csv": "WRONG,weight\n010101,1\n"})
    q = dict(query(fixture_registry), source_path=str(raw))
    dest = tmp_path / "derived.zip"
    assert _download_one(q, dest) == "failed"
    assert not dest.exists()
    write_zip(raw, {"households.csv": "UBIGEO\n010101\n", "new.csv": "UBIGEO\n150101\n"})
    assert _download_one(q, dest) == "failed"
    assert not dest.exists()


def test_reader_api_uses_verified_rule_and_format_specific_source_cache(fixture_registry, tmp_path, monkeypatch):
    source = tmp_path / ".geography-sources/CSV/BASE.zip"
    write_zip(source, {"households.csv": "HHID,UBIGEO,weight\n0001,010101,5\n0002,150101,8\n"})
    network = Mock(side_effect=AssertionError("Use cached original"))
    monkeypatch.setattr("inei_microdatos.download.requests.get", network)
    result = read_catalog_entry(catalog()[0], "2024", ubigeo="010101", dest=tmp_path)
    assert result["households"].HHID.tolist() == ["0001"]
    assert source.exists()
    assert (tmp_path / "BASE-ubigeo-010101.zip").exists()
    scoped = select_geography(catalog(), "010101")
    assert read_catalog_entry(scoped[0], "2024", dest=tmp_path)["households"].attrs["ubigeo"] == "010101"
    with pytest.raises(ValueError, match="original national"):
        select_geography(scoped, "15")
    network.assert_not_called()


def test_custom_layout_isolation_format_fallback_and_dry_run(fixture_registry, tmp_path, capsys):
    scoped = select_geography(catalog(), "01")
    mod = scoped[0]["years"]["2024"]["Annual"]["modules"][0]
    assert module_download(mod, "STATA")[2] == "CSV"
    with pytest.raises(ValueError, match="Derived survey subsets use CSV"):
        module_download(mod, "STATA", fallback=False)
    tasks = _collect_module_tasks(scoped, tmp_path, "CSV", False, "{module_name}.zip")
    q, path = tasks[0]
    assert path == tmp_path / "ubigeo-01/BASE.zip"
    assert ".geography-sources/CSV/BASE.zip" in q["source_path"]
    result = download_modules(catalog("DEP"), tmp_path, ubigeo="010101", dry_run=True)
    assert result == {"files": 0, "would_skip": 0, "unavailable": 1}
    assert "unavailable" in capsys.readouterr().out


def test_shared_source_download_is_serialized(tmp_path, monkeypatch):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("table.csv", "x\n1\n")
    response = Mock(iter_content=Mock(return_value=iter([data.getvalue()])))
    network = Mock(return_value=response)
    monkeypatch.setattr("inei_microdatos.download.requests.get", network)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: _download_one("https://example.org/source", tmp_path / "source.zip"), range(4)))
    assert sorted(outcomes) == ["ok", "skipped", "skipped", "skipped"]
    network.assert_called_once()


def test_bundled_registry_is_scoped_and_covers_each_reviewed_family():
    rules = _registry()
    assert len(rules) == 128
    assert len({r["survey_value"] for r in rules.values()}) == 6
    assert {r["year"] for r in rules.values()} == {"2024"}
    for r in rules.values():
        for t in r["tables"]:
            if t["method"] == "join":
                assert (r["survey_value"], r["year"], r["period"], t["parent_code"]) in rules
    c = filter_catalog(load_catalog(), survey="endes", year_min=2024, year_max=2024)
    assert all(m["geography_support"]["status"] == "verified" for m in c[0]["years"]["2024"]["Unico"]["modules"])


def test_cli_capabilities_and_unsupported_download_are_offline(tmp_path, monkeypatch):
    monkeypatch.setattr("inei_microdatos.download.requests.get", Mock(side_effect=AssertionError("No network")))
    runner = CliRunner()
    result = runner.invoke(cli, ["geography", "--survey", "epen-deptos", "--year-min", "2024", "--year-max", "2024", "--json"])
    assert result.exit_code == 0, result.output
    assert all(c["levels"] == ["department"] for c in json.loads(result.output))
    result = runner.invoke(cli, ["download", "--survey", "epen-deptos", "--year-min", "2024", "--year-max", "2024",
                                 "--ubigeo", "150101", "--dest", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "unavailable" in result.output
