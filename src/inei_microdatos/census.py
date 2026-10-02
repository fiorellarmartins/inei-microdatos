"""Population and housing census catalog across INEI publication systems."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlencode

import requests

CENSUS_LABEL = "CENSOS NACIONALES DE POBLACIÓN Y VIVIENDA"
CENSUS_VALUE = "CPV"
CENSUS_YEARS = (1981, 1993, 2005, 2007, 2017, 2025)
CENSUS_2017 = "https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1544/"
CENSUS_2007 = "https://censos.inei.gob.pe/cpv2007/tabulados/"
QUERY_URLS = {
    1981: "http://censos1.inei.gob.pe/censos1981/redatam/",
    1993: "http://censos1.inei.gob.pe/censos1993/redatam/",
    2005: "http://censos1.inei.gob.pe/Censos2005/redatam/",
    2007: "http://censos1.inei.gob.pe/Censos2007/redatam/",
    2017: "https://censos2017.inei.gob.pe/redatam/",
    2025: "https://redatamcpv2025.inei.gob.pe/",
}
SOURCE_URL = "https://censos2025.inei.gob.pe"
FILE_BASE = (
    "https://proyectos.inei.gob.pe/dir-segmentacion-ci/postcensal/prod/"
    "adjuntos/censos-2025/descarga_datos/tabulados/00"
)
TOPICS = {"poblacion": 948, "hogar": 950, "vivienda": 949}


def _modules_2025() -> list[dict]:
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
    return modules


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and dict(attrs).get("href"):
            self.links.append(dict(attrs)["href"])


def _get_html(url: str, encoding: str = "utf-8") -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.content.decode(encoding)


def _modules_2017() -> list[dict]:
    parser = _Links()
    parser.feed(_get_html(urljoin(CENSUS_2017, "contenido.htm")))
    modules = []
    for link in dict.fromkeys(parser.links):
        match = re.fullmatch(r"cuadros/00TOMO_(\d+)\.xlsx", link, re.I)
        if match:
            volume = match.group(1)
            modules.append({
                "survey_code": "CPV2017",
                "module_code": f"CPV2017-00-tomo-{volume}",
                "module_name": f"Resultados definitivos: Tomo {int(volume)}",
                "csv_code": None, "stata_code": None, "spss_code": None,
                "xlsx_url": urljoin(CENSUS_2017, link),
            })
    if not modules:
        raise ValueError("No national Censo 2017 workbooks found")
    return modules


def _parse_2007_tables(html: str, project: str) -> list[dict]:
    modules = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.I | re.S):
        code = re.search(r"clickRadioCuadro\('([0-9]+)'", row)
        title = re.search(r"<td\s+title='([^']+)'", row, re.I)
        if not code or not title:
            continue
        code = code.group(1)
        modules.append({
            "survey_code": "CPV2007",
            "module_code": f"CPV2007-00-{project}-{code}",
            "module_name": unescape(title.group(1)),
            "csv_code": None, "stata_code": None, "spss_code": None,
            # INEI serves HTML tables under an Excel .xls filename.
            "xls_url": CENSUS_2007 + "Tabla.asp?" + urlencode({
                "proy": project, "u": "00", "cuadro": code, "exportar": "xls",
            }),
            "file_encoding": "windows-1252",
        })
    if not modules:
        raise ValueError(f"No Censo 2007 tables found for project {project}")
    return modules


def _modules_2007() -> list[dict]:
    # Discover thematic projects from the site's own menu.
    html = _get_html(CENSUS_2007)
    projects = list(dict.fromkeys(re.findall(r"cambiarIU\('([0-9]+)'", html)))
    if not projects:
        raise ValueError("No Censo 2007 thematic projects found")
    modules = []
    for project in projects:
        url = CENSUS_2007 + "ListaCuadros.asp?" + urlencode({"proy": project, "anio": "", "iu": ""})
        modules.extend(_parse_2007_tables(_get_html(url, "cp1252"), project))
    return modules


def requested_census_years(surveys=None, years=None) -> list[int]:
    """Apply dataset aliases and year constraints before making network requests."""
    from inei_microdatos.aliases import resolve_alias, ALIAS_YEARS
    selected = set()
    for query in surveys or [CENSUS_LABEL]:
        if resolve_alias(query).lower() in CENSUS_LABEL.lower():
            alias_year = ALIAS_YEARS.get(query.lower())
            selected.update([alias_year] if alias_year else CENSUS_YEARS)
    return [year for year in CENSUS_YEARS if year in selected
            and (not years or years[0] <= year <= years[1])]


def build_census_catalog(years=None) -> dict:
    """Build one dataset with year/period/modules, preserving original tables.

    Older years without a verified download adapter contain explicit REDATAM
    references, not fabricated files. No IPUMS samples are mixed with INEI tables.
    """
    selected = CENSUS_YEARS if years is None else years
    builders = {2007: _modules_2007, 2017: _modules_2017, 2025: _modules_2025}
    sources = {2007: CENSUS_2007, 2017: CENSUS_2017, 2025: SOURCE_URL +
               "/resultados/descarga-de-datos/cuadros-estadisticos/tabulados"}
    year_data = {}
    for year in CENSUS_YEARS:
        if year not in selected:
            continue
        modules = builders[year]() if year in builders else []
        year_data[str(year)] = {"Unico": {
            "period_value": "unico", "modules": modules, "docs": [],
            "access": "download" if modules else "online_query",
            "source_url": sources.get(year, QUERY_URLS[year]),
            "resources": [{"name": "REDATAM", "url": QUERY_URLS[year], "type": "online_query"}],
            "note": "Original national tabulations; layouts and definitions vary by census."
                    if modules else "Online query reference only; automated downloads are not supported for this year.",
        }}
    return {
        "category": "Censos", "value": CENSUS_VALUE, "label": CENSUS_LABEL,
        "data_kind": "aggregate_tables",
        "geography": {"code": "00", "name": "Perú"},
        "source_url": "https://www.inei.gob.pe/estadisticas/censos/",
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "years": year_data,
    }
