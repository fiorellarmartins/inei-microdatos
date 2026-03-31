"""INEI microdatos portal client — handles session, AJAX requests, HTML parsing."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

import requests

BASE_URL = "https://proyectos.inei.gob.pe/microdatos/"
DOWNLOAD_BASE = "https://proyectos.inei.gob.pe/iinei/srienaho/descarga/"
ENTRY_PAGE = "Consulta_por_Encuesta.asp?CU=19558"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Survey:
    category: str        # ENAHO Anterior | ENAHO Actualizada | EPEN | Standalone
    value: str           # the raw <option> value sent to the server
    label: str           # display name

@dataclass
class Period:
    value: str           # period code sent to AJAX
    label: str           # e.g. "Anual - (Ene-Dic)", "Trimestre 1"

@dataclass
class Module:
    survey_code: str     # e.g. "966"
    module_code: str     # e.g. "01", "1629"
    name: str
    csv_code: Optional[str] = None    # e.g. "966-Modulo01"
    stata_code: Optional[str] = None
    spss_code: Optional[str] = None

    def download_url(self, fmt: str = "CSV") -> Optional[str]:
        code = {"CSV": self.csv_code, "STATA": self.stata_code, "SPSS": self.spss_code}.get(fmt.upper())
        if not code:
            return None
        return f"{DOWNLOAD_BASE}{fmt.upper()}/{code}.zip"

@dataclass
class Doc:
    code: str
    name: str
    zip_path: Optional[str] = None        # relative: "2024-5/CuestionarioHogar.zip"
    ficha_params: Optional[list] = None   # [CE, MO, year, period, docname]

    def zip_url(self) -> Optional[str]:
        if not self.zip_path:
            return None
        return f"{DOWNLOAD_BASE}DocumentosZIP/{self.zip_path}"

    def pdf_url(self) -> Optional[str]:
        if not self.ficha_params or len(self.ficha_params) < 2:
            return None
        return f"{BASE_URL}VerificaFicha.asp?CE={self.ficha_params[0]}&MO={self.ficha_params[1]}"

@dataclass
class PeriodData:
    period: Period
    modules: list[Module] = field(default_factory=list)
    docs: list[Doc] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

class _OptionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.options: list[tuple[str, str]] = []
        self._val: Optional[str] = None
        self._text = ""
        self._inside = False

    def handle_starttag(self, tag, attrs):
        if tag == "option":
            self._inside = True
            self._val = dict(attrs).get("value", "")
            self._text = ""

    def handle_data(self, data):
        if self._inside:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "option" and self._inside:
            self.options.append((self._val or "", self._text.strip()))
            self._inside = False


def _parse_options(html: str) -> list[tuple[str, str]]:
    p = _OptionParser()
    p.feed(html)
    return [(v, t) for v, t in p.options if v]


def _parse_modules(html: str) -> list[Module]:
    modules = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(tds) < 7:
            continue
        clean = lambda s: re.sub(r"<[^>]+>", "", s).strip()
        sc, mc, mn = clean(tds[3]), clean(tds[5]), clean(tds[6])
        if not sc or not mc:
            continue
        # Skip header row (contains HTML entities like "Código" or non-numeric codes)
        if not sc.isdigit() or "&" in tds[3]:
            continue
        csv = re.findall(r"descarga/CSV/([^.]+)\.zip", row)
        dta = re.findall(r"descarga/STATA/([^.]+)\.zip", row)
        sps = re.findall(r"descarga/SPSS/([^.]+)\.zip", row)
        modules.append(Module(
            survey_code=sc, module_code=mc, name=mn,
            csv_code=csv[0] if csv else None,
            stata_code=dta[0] if dta else None,
            spss_code=sps[0] if sps else None,
        ))
    return modules


def _parse_docs(html: str) -> list[Doc]:
    docs = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(tds) < 7:
            continue
        clean = lambda s: re.sub(r"<[^>]+>", "", s).strip()
        dc, dn = clean(tds[5]), clean(tds[6])
        if not dc:
            continue
        zips = re.findall(r"/iinei/srienaho/descarga/DocumentosZIP/([^\"'<>\s]+)", row)
        fp = re.findall(r"VerFicha\('([^']+)','([^']+)','([^']+)','([^']+)','([^']+)'\)", row)
        docs.append(Doc(
            code=dc, name=dn,
            zip_path=zips[0] if zips else None,
            ficha_params=list(fp[0]) if fp else None,
        ))
    return docs


# ---------------------------------------------------------------------------
# JS-style escape (critical for Windows-1252 characters like \x96 en-dash)
# ---------------------------------------------------------------------------

def js_escape(s: str) -> str:
    """Replicate JavaScript's escape() — encodes to %XX for chars <= 0xFF,
    %uXXXX for higher. This is required because the INEI server expects
    this encoding, NOT standard UTF-8 percent-encoding."""
    out = []
    for ch in s:
        code = ord(ch)
        if ch.isalnum() or ch in "@*_+-./":
            out.append(ch)
        elif code <= 0xFF:
            out.append(f"%{code:02X}")
        else:
            out.append(f"%u{code:04X}")
    return "".join(out)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class INEIClient:
    """Wraps a requests.Session and provides methods to interact with the
    INEI microdatos AJAX endpoints."""

    def __init__(self, delay: float = 0.2):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/x-www-form-urlencoded"})
        self.delay = delay
        self._initialized = False

    def _ensure_session(self):
        if not self._initialized:
            self.session.get(BASE_URL + ENTRY_PAGE)
            self._initialized = True

    def _post(self, endpoint: str, body: str) -> str:
        self._ensure_session()
        time.sleep(self.delay)
        r = self.session.post(
            BASE_URL + endpoint,
            data=body.encode("latin-1"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        r.raise_for_status()
        return r.content.decode("latin-1")

    def get_surveys(self) -> list[Survey]:
        """Return all available surveys from the main page dropdowns."""
        self._ensure_session()
        r = self.session.get(BASE_URL + ENTRY_PAGE)
        html = r.content.decode("latin-1")

        def _extract_select(name: str) -> list[tuple[str, str]]:
            m = re.search(
                rf'<select[^>]*(?:name|id)=["\']' + name + r'["\'][^>]*>(.*?)</select>',
                html, re.DOTALL | re.I,
            )
            return _parse_options(m.group(1)) if m else []

        main = _extract_select("cmbEncuesta0ID")
        sub_n = _extract_select("cmbEncuestaN")
        sub_a = _extract_select("cmbEncuestaA")
        sub_epe = _extract_select("cmbEncuesta_EPE")

        surveys = []
        for val, label in main:
            if val == "1":
                for sv, sl in sub_n:
                    surveys.append(Survey("ENAHO Anterior", sv, sl))
            elif val == "2":
                for sv, sl in sub_a:
                    surveys.append(Survey("ENAHO Actualizada", sv, sl))
            elif val == "3":
                for sv, sl in sub_epe:
                    surveys.append(Survey("EPEN", sv, sl))
            else:
                surveys.append(Survey("Standalone", val, label))
        return surveys

    def get_years(self, survey: Survey) -> list[str]:
        """Return available years for a survey."""
        enc = js_escape(survey.value)
        html = self._post("CambiaEnc.asp", f"bandera=1&_cmbEncuesta={enc}")
        return [v for v, _ in _parse_options(html)]

    def get_periods(self, survey: Survey, year: str) -> list[Period]:
        """Return available periods for a survey-year."""
        enc = js_escape(survey.value)
        html = self._post(
            "CambiaAnio.asp",
            f"bandera=1&_cmbEncuesta={enc}&_cmbAnno={year}&_cmbEncuesta0={enc}",
        )
        return [Period(value=v, label=t) for v, t in _parse_options(html)]

    def get_modules(self, survey: Survey, year: str, period: Period) -> list[Module]:
        """Return downloadable modules for a survey-year-period."""
        enc = js_escape(survey.value)
        html = self._post(
            "cambiaPeriodo.asp",
            f"bandera=1&_cmbEncuesta={enc}&_cmbAnno={year}&_cmbTrimestre={js_escape(period.value)}",
        )
        return _parse_modules(html)

    def get_docs(self, survey: Survey, year: str, period: Period) -> list[Doc]:
        """Return documentation files for a survey-year-period."""
        enc = js_escape(survey.value)
        html = self._post(
            "CambiaPeriodoDoc.asp",
            f"bandera=1&_cmbEncuesta={enc}&_cmbAnno={year}&_cmbTrimestre={js_escape(period.value)}",
        )
        return _parse_docs(html)
