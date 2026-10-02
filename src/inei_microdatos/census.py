"""National Censo 2025 tabulations, published outside the Microdatos portal."""

from datetime import datetime, timezone
from urllib.parse import quote

import requests

CENSUS_LABEL = "CENSOS NACIONALES 2025 - Tabulados agregados (Perú)"
CENSUS_VALUE = "CPV2025-TABULADOS"
SOURCE_URL = "https://censos2025.inei.gob.pe"
FILE_BASE = (
    "https://proyectos.inei.gob.pe/dir-segmentacion-ci/postcensal/prod/"
    "adjuntos/censos-2025/descarga_datos/tabulados/00"
)
TOPICS = {"poblacion": 948, "hogar": 950, "vivienda": 949}


def build_census_catalog() -> dict:
    """Discover national XLSX tables; these are aggregates, not microdata.

    Fail on an invalid/empty response rather than saving an incomplete catalog.
    No authentication or Microdatos ASP session is needed.
    """
    modules = []
    for group, topic in TOPICS.items():
        response = requests.get(
            f"{SOURCE_URL}/api/v1/catalogo/datos-documentos/{topic}", timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is not True or not payload.get("data"):
            raise ValueError(f"Missing Censo 2025 table catalog: {group}")
        for item in payload["data"]:
            route = item.get("ruta")
            if not route or not item.get("peso"):
                continue  # The website only offers downloads for these rows.
            modules.append({
                "survey_code": "CPV2025",
                "module_code": f"CPV2025-00-{group}-{item['idTema']}",
                "module_name": f"{group.capitalize()}: {item['nombDato']}",
                "csv_code": None,
                "stata_code": None,
                "spss_code": None,
                "xlsx_url": f"{FILE_BASE}/{group}/{quote(route, safe='')}.xlsx",
            })
        if not any(m["module_code"].startswith(f"CPV2025-00-{group}-") for m in modules):
            raise ValueError(f"No downloadable Censo 2025 tables: {group}")
    return {
        "category": "Tabulados",
        "value": CENSUS_VALUE,
        "label": CENSUS_LABEL,
        "data_kind": "aggregate_tables",
        "geography": {"code": "00", "name": "Perú"},
        "source_url": f"{SOURCE_URL}/resultados/descarga-de-datos/cuadros-estadisticos/tabulados",
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "years": {"2025": {"Unico": {
            "period_value": "unico", "modules": modules, "docs": [],
        }}},
    }
