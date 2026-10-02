"""Census integration: aggregate metadata, format selection, and workbook reading."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from inei_microdatos.catalog import build_catalog, catalog_stats, filter_catalog, load_catalog
from inei_microdatos.census import TOPICS, build_census_catalog
from inei_microdatos.cli import cli
from inei_microdatos.download import LAYOUTS, _collect_module_tasks, _download_one, download_modules
from inei_microdatos.reader import list_tables, read_catalog_entry, read_module


@pytest.fixture
def census():
    return deepcopy(filter_catalog(load_catalog(), survey="censo2025"))


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "tables.xlsx"
    wb = Workbook()
    wb.active.title = "CUADRO 1"
    wb.active.append(["Población censada", None])
    wb.active.append(["Total", 32706028])
    wb.create_sheet("Notas").append(["Tabulados agregados"])
    wb.save(path)
    return path


def test_bundled_census(census):
    assert len(census) == 1
    assert census[0]["data_kind"] == "aggregate_tables"
    assert census[0]["geography"]["code"] == "00"
    assert filter_catalog(census, survey="cpv2025") == census
    assert filter_catalog(census, year_max=2024) == []
    mods = census[0]["years"]["2025"]["Unico"]["modules"]
    assert len(mods) == 11
    assert len({m["module_code"] for m in mods}) == len(mods)
    assert all(m["xlsx_url"].endswith(".xlsx") and not m["csv_code"] for m in mods)
    assert catalog_stats(census)["downloadable_modules"] == 11


def test_census_discovery(monkeypatch):
    get = Mock()
    get.return_value.json.return_value = {"success": True, "data": [
        {"idTema": 1, "nombDato": "Educación", "ruta": "Educación", "peso": "1 MB"},
        {"idTema": 2, "nombDato": "Pending", "ruta": None, "peso": None},
    ]}
    monkeypatch.setattr("inei_microdatos.census.requests.get", get)
    result = build_census_catalog()
    mods = result["years"]["2025"]["Unico"]["modules"]
    assert len(mods) == 3
    assert all("Educaci%C3%B3n.xlsx" in m["xlsx_url"] for m in mods)
    assert {c.args[0].split("/")[-1] for c in get.call_args_list} == {str(t) for t in TOPICS.values()}
    get.return_value.json.return_value = {"success": False, "data": []}
    with pytest.raises(ValueError, match="Missing Censo"):
        build_census_catalog()


def test_crawl_routing(monkeypatch, census):
    discover = Mock(return_value=census[0])
    monkeypatch.setattr("inei_microdatos.census.build_census_catalog", discover)
    client = Mock()
    client.get_surveys.return_value = []
    assert build_catalog(client, surveys=["censo2025"], progress=False) == census
    client.get_surveys.assert_not_called()
    discover.assert_called_once()
    discover.reset_mock()
    assert build_catalog(client, surveys=["cpv2025"], years=(2020, 2024), progress=False) == []
    assert build_catalog(client, surveys=["endes"], progress=False) == []
    discover.assert_not_called()
    assert build_catalog(client, progress=False) == census


@pytest.mark.parametrize("layout", list(LAYOUTS.values()) + ["{year}/{module_name}.zip"])
def test_xlsx_layout_and_strict_format(census, tmp_path, layout):
    tasks = _collect_module_tasks(census, tmp_path, "XLSX", False, layout)
    assert len(tasks) == 11
    assert len({path for _, path in tasks}) == 11
    assert all(path.suffix == ".xlsx" for _, path in tasks)
    assert _collect_module_tasks(census, tmp_path, "CSV", False, layout) == []
    assert _collect_module_tasks(census, tmp_path, "CSV", True, layout) == tasks


def test_legacy_zip_download_unchanged(tmp_path):
    from test_catalog import SAMPLE_CATALOG
    tasks = _collect_module_tasks(SAMPLE_CATALOG, tmp_path, "CSV", True, LAYOUTS["default"])
    assert len(tasks) == 4
    assert tasks[0][0].endswith("/CSV/968-Modulo1629.zip")
    assert tasks[0][1].suffix == ".zip"
    assert _collect_module_tasks(SAMPLE_CATALOG, tmp_path, "XLSX", False, LAYOUTS["default"]) == []


def test_download_and_read_workbook(census, workbook, tmp_path, monkeypatch):
    response = Mock()
    response.iter_content.return_value = [workbook.read_bytes()]
    get = Mock(return_value=response)
    monkeypatch.setattr("inei_microdatos.download.requests.get", get)
    census[0]["years"]["2025"]["Unico"]["modules"] = census[0]["years"]["2025"]["Unico"]["modules"][:1]
    result = download_modules(census, tmp_path / "downloads", fmt="XLSX", progress=False)
    assert result == {"ok": 1, "skipped": 0, "failed": 0, "bad_zip": 0}
    assert download_modules(census, tmp_path / "downloads", fmt="XLSX", progress=False)["skipped"] == 1
    sheets = read_catalog_entry(census[0], "2025", dest=tmp_path / "cache")
    assert sheets["CUADRO 1"].iloc[0, 0] == "Población censada"  # do not discard title as a header
    assert sheets["CUADRO 1"].iloc[1, 1] == 32706028
    assert list(read_module(workbook, tables=["notas"])) == ["Notas"]
    assert [s["name"] for s in list_tables(workbook)] == ["CUADRO 1", "Notas"]
    # INEI sometimes serves an HTML error with HTTP 200; don't retain it.
    response.iter_content.return_value = [b"<html>Not found</html>"]
    bad = tmp_path / "bad.xlsx"
    assert _download_one("https://example.com/file.xlsx", bad) == "bad_zip"
    assert not bad.exists()


def test_cli_census_and_workbook(census, workbook, tmp_path):
    from inei_microdatos.catalog import save_catalog
    catalog = tmp_path / "catalog.json"
    save_catalog(census, catalog)
    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--catalog", str(catalog), "--survey", "censo2025"])
    assert result.exit_code == 0
    assert "Aggregated tables | XLSX" in result.output
    result = runner.invoke(cli, ["download", "--catalog", str(catalog), "--survey", "cpv2025", "--format", "XLSX", "--dest", str(tmp_path / "out"), "--dry-run"])
    assert result.exit_code == 0
    assert "11 files to download" in result.output
    result = runner.invoke(cli, ["read", str(workbook), "--table", "CUADRO"])
    assert result.exit_code == 0, result.output
    assert "32706028" in result.output
    result = runner.invoke(cli, ["read", str(workbook), "--info"])
    assert result.exit_code == 0
    assert "Notas" in result.output


def test_aggregate_tables_are_not_variable_indexed(census):
    from inei_microdatos.variables import _collect_modules
    assert _collect_modules(census) == []


def test_legacy_spss_fallback_prefers_stata():
    from inei_microdatos.download import module_download
    selected = module_download({"csv_code": "csv", "stata_code": "stata"}, "SPSS")
    assert selected[2] == "STATA"
