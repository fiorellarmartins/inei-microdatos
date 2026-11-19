"""Optional dependency checks and their user-facing error messages."""

import io

import pytest

from inei_microdatos import _dependencies as deps
from inei_microdatos._dependencies import (
    ModuleUpgradeRequiredError,
    OptionalDependencyMissingError,
    assert_optional_import,
)
from inei_microdatos.census_index import workbook_tables
from inei_microdatos.reader import _read_data, read_module
from inei_microdatos.variables import build_index


def block_module(monkeypatch, module_name):
    """Make one optional module unavailable without uninstalling it.

    Only ``_dependencies.import_module`` is patched, which is the seam used by
    ``assert_optional_import``. The module and its submodules raise
    ``ModuleNotFoundError``; every other import is delegated to the real
    ``importlib.import_module``. Code that imports a dependency directly is
    unaffected, so real absence is covered by the minimal CI job instead.
    ``monkeypatch`` reverts the patch after each test, and repeated calls stack
    blockers.
    """
    real_import = deps.import_module

    def fake_import(name, *args, **kwargs):
        if name == module_name or name.startswith(module_name + "."):
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(deps, "import_module", fake_import)


def show_message(excinfo):
    """Print a captured error so it is visible with ``pytest -s``."""
    print(f"\n{excinfo.type.__name__}:\n{excinfo.value}\n")


def test_missing_dependency_message_mentions_extra(monkeypatch):
    block_module(monkeypatch, "pandas")
    with pytest.raises(OptionalDependencyMissingError) as excinfo:
        assert_optional_import("pandas", extra="pandas", min_version="1.2")
    show_message(excinfo)
    excinfo.match(r"inei-microdatos\[pandas\]")


def test_internal_import_error_is_not_hidden(monkeypatch):
    def fake_import(name, *args, **kwargs):
        raise ModuleNotFoundError("No module named 'numpy'", name="numpy")

    monkeypatch.setattr(deps, "import_module", fake_import)
    with pytest.raises(ModuleNotFoundError) as excinfo:
        assert_optional_import("pandas", extra="pandas")
    show_message(excinfo)
    assert excinfo.value.name == "numpy"


def test_read_module_checks_pandas_before_touching_source(monkeypatch, tmp_path):
    block_module(monkeypatch, "pandas")
    with pytest.raises(OptionalDependencyMissingError) as excinfo:
        read_module(tmp_path / "does-not-exist.zip")
    show_message(excinfo)
    excinfo.match(r"inei-microdatos\[pandas\]")


def test_spss_requires_pyreadstat(monkeypatch):
    pytest.importorskip("pandas")
    block_module(monkeypatch, "pyreadstat")
    with pytest.raises(OptionalDependencyMissingError) as excinfo:
        _read_data(io.BytesIO(b""), "spss", "sample.sav")
    show_message(excinfo)
    excinfo.match("pyreadstat")


def test_build_index_requires_pyreadstat_before_downloading(monkeypatch, tmp_path):
    block_module(monkeypatch, "pyreadstat")
    catalog = [{
        "value": "Example",
        "label": "Example",
        "category": "Household",
        "years": {"2024": {"Annual": {"modules": [
            {"module_code": "1", "module_name": "Example module", "stata_code": "1"},
        ]}}},
    }]
    with pytest.raises(OptionalDependencyMissingError) as excinfo:
        build_index(catalog, dest=tmp_path / "index.gz", progress=False)
    show_message(excinfo)
    excinfo.match("pyreadstat")


def test_census_workbook_requires_openpyxl(monkeypatch, tmp_path):
    block_module(monkeypatch, "openpyxl")
    with pytest.raises(OptionalDependencyMissingError) as excinfo:
        workbook_tables(tmp_path / "sample.xlsx")
    show_message(excinfo)
    excinfo.match("openpyxl")


def test_legacy_xls_validation_does_not_require_pandas(monkeypatch, tmp_path):
    from inei_microdatos.download import _valid_download
    from inei_microdatos.reader import list_tables

    block_module(monkeypatch, "pandas")
    block_module(monkeypatch, "openpyxl")
    path = tmp_path / "legacy.xls"
    path.write_bytes(
        b"<table id='tabDetalle'><tr><td>PERU</td><td>1</td></tr></table>"
    )
    assert _valid_download(path)
    assert list_tables(path)[0]["name"] == "tabDetalle"


def test_build_index_requires_openpyxl_for_census_workbooks(monkeypatch, tmp_path):
    block_module(monkeypatch, "openpyxl")
    catalog = [{
        "value": "Census",
        "label": "Census",
        "category": "Census",
        "data_kind": "aggregate_tables",
        "years": {"2025": {"Unico": {"source_url": "https://example.org/", "modules": [
            {"module_code": "1", "module_name": "Example table", "xlsx_url": "https://example.org/1.xlsx"},
        ]}}},
    }]
    with pytest.raises(OptionalDependencyMissingError) as excinfo:
        build_index(catalog, dest=tmp_path / "index.gz", progress=False)
    show_message(excinfo)
    excinfo.match("openpyxl")


def test_old_dependency_version_raises(monkeypatch):
    monkeypatch.setattr(deps, "distribution_version", lambda dist: "0.1")
    with pytest.raises(ModuleUpgradeRequiredError) as excinfo:
        assert_optional_import("packaging", extra="pandas", min_version="21")
    show_message(excinfo)
    excinfo.match("packaging>=21")


def test_cli_reports_missing_optional_dependency(monkeypatch):
    from click.testing import CliRunner

    from inei_microdatos.cli import cli

    block_module(monkeypatch, "pandas")
    result = CliRunner().invoke(cli, ["read", "example.zip"])
    print(f"\nCLI output:\n{result.output}\n")
    assert result.exit_code != 0
    assert "inei-microdatos[pandas]" in result.output
