"""Discover and export national frequency tables from INEI's legacy REDATAM."""

from __future__ import annotations

import threading
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from lxml import html

ENGINE = "http://censos1.inei.gob.pe/cgibin/RpWebEngine.exe/Frequency"
GROUPS = {"FREQVIV": "Vivienda", "FREQHOG": "Hogar", "FREQPER": "Población"}
# The legacy service uses temporary server files. Keep each export sequence
# together and avoid sending concurrent census computations to the old engine.
_LOCK = threading.Lock()


def parse_frequency_form(content: bytes, year: int, item: str) -> list[dict]:
    root = html.fromstring(content.decode("cp1252"))
    forms = root.xpath("//form")
    if not forms:
        raise ValueError(f"Missing REDATAM form: {year}/{item}")
    form = forms[0]
    params = {node.get("name"): node.get("value", "")
              for node in form.xpath(".//input[@name]")
              if node.get("type", "").lower() == "hidden"}
    if params.get("BASE") != f"CPV{year}" or params.get("ITEM") != item:
        raise ValueError("Unexpected REDATAM census form")
    params.update(MODE="RUN", TITLE="", AREABREAK="", SELECT="ALL", SUBMIT="Ejecutar")
    # Preserve hidden WEIGHT, notably PERSONA.FACTEXP for the 1981 census.
    modules = []
    for node in form.xpath('.//select[@name="VARIABLE"]/option[@value]'):
        variable = node.get("value")
        modules.append({
            "survey_code": f"CPV{year}",
            "module_code": f"CPV{year}-00-{item}-{variable}",
            "module_name": f"{GROUPS[item]}: {' '.join(node.text_content().split())}",
            "csv_code": None, "stata_code": None, "spss_code": None,
            "redatam_query": {"url": ENGINE, "data": dict(params, VARIABLE=variable)},
            "file_encoding": "windows-1252",
            "file_content": "sylk",
        })
    if not modules:
        raise ValueError(f"No REDATAM frequency variables: {year}/{item}")
    return modules


def discover_modules(year: int) -> list[dict]:
    modules = []
    for item in GROUPS:
        response = requests.get(ENGINE + "?" + urlencode({
            "BASE": f"CPV{year}", "ITEM": item, "MAIN": "WebServerMain.inl",
        }), timeout=30)
        response.raise_for_status()
        modules.extend(parse_frequency_form(response.content, year, item))
    return modules


def _output_url(base: str, link: str) -> str:
    url = urljoin(base, link.strip())
    parsed = urlsplit(url)
    if parsed.hostname != "censos1.inei.gob.pe" or not parsed.path.startswith("/cgibin/"):
        raise ValueError("Unexpected REDATAM output URL")
    return url


def export_excel(query: dict) -> bytes:
    """Run a fresh query and fetch its transient export; never cache temp URLs."""
    if query["url"] != ENGINE:
        raise ValueError("Unexpected REDATAM query endpoint")
    with _LOCK, requests.Session() as session:
        result = session.post(ENGINE, data=query["data"], timeout=120)
        result.raise_for_status()
        root = html.fromstring(result.content.decode("cp1252"))
        frames = root.xpath("//iframe/@src")
        if len(frames) != 1:
            raise ValueError("REDATAM did not return one frequency table")
        output = session.get(_output_url(ENGINE, frames[0]), timeout=120)
        output.raise_for_status()
        root = html.fromstring(output.content.decode("cp1252"))
        links = [link for link in root.xpath("//a/@href")
                 if urlsplit(link).path.lower().endswith("/reporte.xls")]
        if len(links) != 1:
            raise ValueError("REDATAM did not provide an Excel export")
        export = session.get(_output_url(ENGINE, links[0]), timeout=120)
        export.raise_for_status()
        if not export.content.startswith(b"ID;"):
            raise ValueError("REDATAM returned an invalid SYLK Excel export")
        return export.content
