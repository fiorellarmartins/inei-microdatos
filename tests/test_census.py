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
    result = build_census_catalog(years=[2025])
    mods = result["years"]["2025"]["Unico"]["modules"]
    assert len(mods) == 3
    assert all("Educaci%C3%B3n.xlsx" in m["xlsx_url"] for m in mods)
    assert {c.args[0].split("/")[-1] for c in get.call_args_list} == {str(t) for t in TOPICS.values()}
    get.return_value.json.return_value = {"success": False, "data": []}
    with pytest.raises(ValueError, match="Missing Censo"):
        build_census_catalog(years=[2025])


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
    assert "Aggregated tables" in result.output
    assert "2025: 11 modules | XLSX" in result.output
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


def test_unified_census_years_and_aliases():
    entries = filter_catalog(load_catalog(), survey="censo")
    assert len(entries) == 1
    assert set(entries[0]["years"]) == {"1981", "1993", "2005", "2007", "2017", "2025"}
    for alias, year in [("censo2017", "2017"), ("cpv2007", "2007"), ("censo2025", "2025")]:
        assert list(filter_catalog(entries, survey=alias)[0]["years"]) == [year]
    assert filter_catalog(entries, survey="cpv2017", year_min=2025) == []
    assert list(filter_catalog(entries, survey="censo", year_min=2017)[0]["years"]) == ["2017", "2025"]
    for year in ("1981", "1993", "2005"):
        period = entries[0]["years"][year]["Unico"]
        assert period["access"] == "online_query"
        assert period["modules"] == []
        assert period["resources"][0]["url"].startswith("http://censos1.inei.gob.pe/")


def test_year_filter_applied_before_discovery(monkeypatch):
    from inei_microdatos.census import requested_census_years
    assert requested_census_years(["censo"], (2000, 2020)) == [2005, 2007, 2017]
    assert requested_census_years(["cpv2017", "cpv2025"], (2010, 2020)) == [2017]
    assert requested_census_years(["endes"]) == []
    builder = Mock(return_value=[])
    monkeypatch.setattr("inei_microdatos.census._modules_2025", builder)
    result = build_census_catalog(years=[1981])
    builder.assert_not_called()
    assert list(result["years"]) == ["1981"]


def test_2017_discovery_national_only(monkeypatch):
    html = '<a href="cuadros/00TOMO_01.xlsx">Excel</a>' * 2
    html += '<a href="00TOMO_01.pdf">PDF</a><a href="cuadros/03TOMO_01.xlsx">Regional</a>'
    monkeypatch.setattr("inei_microdatos.census._get_html", lambda url: html)
    result = build_census_catalog(years=[2017])
    modules = result["years"]["2017"]["Unico"]["modules"]
    assert len(modules) == 1
    assert modules[0]["module_code"] == "CPV2017-00-tomo-01"
    assert modules[0]["xlsx_url"].endswith("Lib1544/cuadros/00TOMO_01.xlsx")


def test_2007_discovery(monkeypatch):
    from inei_microdatos.census import CENSUS_2007
    html = """<tr><td><input onclick=javascript:clickRadioCuadro('001','3')></td>
    <td title='VIVIENDAS &amp; HOGARES'>Short label</td></tr>"""
    get = Mock(side_effect=["cambiarIU('001','VIVIENDA','title')", html])
    monkeypatch.setattr("inei_microdatos.census._get_html", get)
    result = build_census_catalog(years=[2007])
    mod = result["years"]["2007"]["Unico"]["modules"][0]
    assert mod["module_code"] == "CPV2007-00-001-001"
    assert mod["module_name"] == "VIVIENDAS & HOGARES"
    assert mod["xls_url"] == CENSUS_2007 + "Tabla.asp?proy=001&u=00&cuadro=001&exportar=xls"
    assert not mod.get("xlsx_url")


def test_legacy_html_excel_download_read_and_reject_error(tmp_path, monkeypatch):
    from inei_microdatos.download import _valid_download
    html = """<table id='tabDetalle'><thead><tr><td>Área</td><td>Total</td></tr></thead>
    <tbody><tr><td>PERÚ</td><td>7566142</td></tr></tbody></table>"""
    response = Mock()
    response.iter_content.return_value = [html.encode("cp1252")]
    monkeypatch.setattr("inei_microdatos.download.requests.get", Mock(return_value=response))
    path = tmp_path / "legacy.xls"
    assert _download_one("https://example.com/Tabla.asp", path) == "ok"
    frame = read_module(path)["tabDetalle"]
    assert frame.iloc[0, 0] == "Área"
    assert frame.iloc[1, 0] == "PERÚ"
    assert str(frame.iloc[1, 1]) == "7566142"
    assert list_tables(path)[0]["format"] == "xls"
    assert list(read_module(path, tables=["tabDetalle"])) == ["tabDetalle"]
    assert read_module(path, tables=["absent"]) == {}
    path.write_text("<html>Microsoft OLE DB Provider error</html>")
    assert not _valid_download(path)
    response.iter_content.return_value = [b"<html>Server error</html>"]
    assert _download_one("https://example.com/Tabla.asp", path) == "bad_zip"
    assert not path.exists()


def test_query_only_cli_explains_missing_download(tmp_path):
    from inei_microdatos.catalog import save_catalog
    catalog = tmp_path / "catalog.json"
    save_catalog(filter_catalog(load_catalog(), survey="cpv1981"), catalog)
    result = CliRunner().invoke(cli, ["download", "--catalog", str(catalog),
                                    "--survey", "censo", "--dest", str(tmp_path / "out")])
    assert result.exit_code == 0
    assert "1981: online query only" in result.output
    assert "censos1981/redatam/" in result.output
    assert not (tmp_path / "out").exists()


def test_historical_download_counts_and_formats(tmp_path):
    catalog = filter_catalog(load_catalog(), survey="censo", year_min=2007, year_max=2017)
    assert list(catalog[0]["years"]) == ["2007", "2017"]
    assert all(list(periods) == ["Unico"] for periods in catalog[0]["years"].values())
    tasks = _collect_module_tasks(catalog, tmp_path, "CSV", True, LAYOUTS["default"])
    assert len(tasks) == 108
    assert len({path for _, path in tasks}) == 108
    assert sum(path.suffix == ".xls" for _, path in tasks) == 103
    assert sum(path.suffix == ".xlsx" for _, path in tasks) == 5
    assert _collect_module_tasks(catalog, tmp_path, "CSV", False, LAYOUTS["default"]) == []
    assert len(_collect_module_tasks(catalog, tmp_path, "XLS", False, LAYOUTS["default"])) == 103
    assert len(_collect_module_tasks(catalog, tmp_path, "XLSX", False, LAYOUTS["default"])) == 5
