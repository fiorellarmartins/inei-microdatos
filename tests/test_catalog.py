"""Tests for catalog module."""

import json
import tempfile
from pathlib import Path

from inei_microdatos.catalog import (
    catalog_stats,
    filter_catalog,
    load_catalog,
    save_catalog,
)

SAMPLE_CATALOG = [
    {
        "category": "Standalone",
        "value": "ENDES",
        "label": "Encuesta Demográfica y de Salud Familiar - ENDES",
        "years": {
            "2024": {
                "Unico": {
                    "period_value": "5",
                    "modules": [
                        {"survey_code": "968", "module_code": "1629", "module_name": "Hogar",
                         "csv_code": "968-Modulo1629", "stata_code": "968-Modulo1629", "spss_code": "968-Modulo1629"},
                        {"survey_code": "968", "module_code": "1630", "module_name": "Vivienda",
                         "csv_code": "968-Modulo1630", "stata_code": None, "spss_code": None},
                    ],
                    "docs": [
                        {"doc_code": "01", "doc_name": "Cuestionario", "zip_path": "2024-5/Cuestionario.zip",
                         "ficha_params": None},
                    ],
                }
            },
            "2023": {
                "Unico": {
                    "period_value": "5",
                    "modules": [
                        {"survey_code": "950", "module_code": "1500", "module_name": "Hogar",
                         "csv_code": "950-Modulo1500", "stata_code": None, "spss_code": None},
                    ],
                    "docs": [],
                }
            },
        },
    },
    {
        "category": "ENAHO Actualizada",
        "value": "ENAHO",
        "label": "Condiciones de Vida y Pobreza - ENAHO",
        "years": {
            "2024": {
                "Anual": {
                    "period_value": "55",
                    "modules": [
                        {"survey_code": "966", "module_code": "01", "module_name": "Mod01",
                         "csv_code": "966-Modulo01", "stata_code": "966-Modulo01", "spss_code": "966-Modulo01"},
                    ],
                    "docs": [],
                }
            },
        },
    },
]


def test_catalog_stats():
    s = catalog_stats(SAMPLE_CATALOG)
    assert s["surveys"] == 2
    assert s["survey_years"] == 3
    assert s["modules"] == 4
    assert s["docs"] == 1
    assert s["downloadable_modules"] == 4  # all have csv_code


def test_filter_by_survey():
    result = filter_catalog(SAMPLE_CATALOG, survey="ENDES")
    assert len(result) == 1
    assert "ENDES" in result[0]["label"]


def test_filter_by_year():
    result = filter_catalog(SAMPLE_CATALOG, year_min=2024)
    assert all("2023" not in e["years"] for e in result)


def test_filter_by_period():
    result = filter_catalog(SAMPLE_CATALOG, period="Anual")
    assert len(result) == 1
    assert "ENAHO" in result[0]["label"]


def test_save_and_load(tmp_path):
    path = tmp_path / "test_catalog.json"
    save_catalog(SAMPLE_CATALOG, path)
    loaded = load_catalog(path)
    assert len(loaded) == 2
    assert loaded[0]["label"] == SAMPLE_CATALOG[0]["label"]


def test_load_legacy_format(tmp_path):
    path = tmp_path / "legacy.json"
    with open(path, "w") as f:
        json.dump(SAMPLE_CATALOG, f)
    loaded = load_catalog(path)
    assert len(loaded) == 2
