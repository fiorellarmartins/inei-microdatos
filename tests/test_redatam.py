"""Legacy REDATAM form defaults, transient exports, and SYLK reading."""

from unittest.mock import Mock

import pytest
import requests

from inei_microdatos.download import _download_one, _valid_download, module_download
from inei_microdatos.reader import list_tables, read_module
from inei_microdatos.redatam import ENGINE, export_excel, parse_frequency_form

FORM = b'''<form method="POST">
<input type="hidden" name="BASE" value="CPV1981">
<input type="hidden" name="MAIN" value="WebServerMain.inl">
<input type="hidden" name="ITEM" value="FREQPER">
<input type="hidden" name="WEIGHT" value="PERSONA.FACTEXP">
<select name="VARIABLE"><option value="PERSONA.SEXO">Sexo
<option value="PERSONA.EDAD">Edad</select></form>'''
SYLK = ('ID;PWXL;N;E\r\nC;Y1;X1;K"Sexo"\r\n'
        'C;Y3;X1;K"Categorías"\r\nC;Y3;X2;K"Casos"\r\n'
        'C;Y4;X1;K"Hombre"\r\nC;Y4;X2;K7931137.00\r\n'
        'C;Y5;X1;K"Mujer"\r\nC;Y5;X2;K7977404.00\r\n'
        'C;Y6;X1;K"Total"\r\nC;Y6;X2;K15908541.00\r\n'
        'C;Y8;X1;K"INEI - CPV1981"\r\nE\r\n').encode("cp1252")


def test_discovery_preserves_weights_and_national_selection():
    modules = parse_frequency_form(FORM, 1981, "FREQPER")
    assert len(modules) == 2
    assert modules[0]["module_name"] == "Población: Sexo"
    query = modules[0]["redatam_query"]
    assert query["data"]["WEIGHT"] == "PERSONA.FACTEXP"
    assert query["data"]["SELECT"] == "ALL"
    assert query["data"]["AREABREAK"] == ""
    assert query["data"]["VARIABLE"] == "PERSONA.SEXO"
    assert module_download(modules[0], "CSV")[0] == query
    assert module_download(modules[0], "CSV", False) is None
    assert module_download(modules[0], "XLS", False)[3] == ".xls"
    with pytest.raises(ValueError, match="Unexpected"):
        parse_frequency_form(FORM, 1993, "FREQPER")
    with pytest.raises(ValueError, match="No REDATAM"):
        parse_frequency_form(FORM.replace(b'"VARIABLE"', b'"OTHER"'), 1981, "FREQPER")


def session_responses(monkeypatch, export=SYLK):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = Mock(content=b'<iframe src="http://censos1.inei.gob.pe/cgibin/WebUtilities.exe/Text?LFN=temporary.htm"></iframe>')
    session.get.side_effect = [
        Mock(content=b'<a href="http://censos1.inei.gob.pe/cgibin/WebUtilities.exe/reporte.xls?LFN=temporary.xls">Excel</a>'),
        Mock(content=export),
    ]
    monkeypatch.setattr("inei_microdatos.redatam.requests.Session", Mock(return_value=session))
    return session


def test_export_download_read_and_cache(monkeypatch, tmp_path):
    query = parse_frequency_form(FORM, 1981, "FREQPER")[0]["redatam_query"]
    session = session_responses(monkeypatch)
    path = tmp_path / "1981.xls"
    assert _download_one(query, path) == "ok"
    assert path.read_bytes() == SYLK
    session.post.assert_called_once_with(ENGINE, data=query["data"], timeout=120)
    assert _download_one(query, path) == "skipped"
    assert session.post.call_count == 1
    frame = read_module(path)["REDATAM"]
    assert frame.shape == (8, 2)
    assert frame.iat[0, 0] == "Sexo"
    assert frame.iat[2, 0] == "Categorías"
    assert frame.iat[5, 1] == 15908541
    assert frame.iat[7, 0] == "INEI - CPV1981"
    assert list_tables(path)[0]["name"] == "REDATAM"
    assert read_module(path, tables=["absent"]) == {}


def test_transient_failure_reruns_query(monkeypatch, tmp_path):
    query = parse_frequency_form(FORM, 1981, "FREQPER")[0]["redatam_query"]
    session = session_responses(monkeypatch)
    good = list(session.get.side_effect)
    session.get.side_effect = [requests.Timeout(), *good]
    assert _download_one(query, tmp_path / "retry.xls") == "ok"
    assert session.post.call_count == 2


@pytest.mark.parametrize("payload", [b"<html>Error</html>", SYLK[:-3],
                                       b'ID;PWXL\nC;Y1;X1;K1;EEXEC()\nE\n'])
def test_invalid_exports_rejected(payload, tmp_path):
    path = tmp_path / "bad.xls"
    path.write_bytes(payload)
    assert not _valid_download(path)


def test_missing_export_and_foreign_output_rejected(monkeypatch):
    query = parse_frequency_form(FORM, 1981, "FREQPER")[0]["redatam_query"]
    session = session_responses(monkeypatch)
    session.get.side_effect = [Mock(content=b"<html>Query failed</html>")]
    with pytest.raises(ValueError, match="Excel export"):
        export_excel(query)
    session.post.return_value.content = b'<iframe src="https://example.com/file"></iframe>'
    with pytest.raises(ValueError, match="output URL"):
        export_excel(query)
