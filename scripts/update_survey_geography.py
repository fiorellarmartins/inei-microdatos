"""Audit CSV archive headers against reviewed, year-specific geographic rules.

Run with --data-dir containing the official CSV ZIPs. This script does not infer
geographic semantics for new surveys or years. Review RULES and sources first.
"""
from __future__ import annotations

import argparse
import codecs
import csv
import json
from pathlib import Path
import zipfile

from inei_microdatos.catalog import load_catalog
from inei_microdatos.client import DOWNLOAD_BASE

DOC = DOWNLOAD_BASE + "DocumentosZIP/"
RULES = {
    "Condiciones de Vida y Pobreza - ENAHO": ("enaho", "household_location", ["2024-55/20_Diccionario_2024.zip"]),
    "Encuesta Demográfica y de Salud Familiar - ENDES": ("endes", "household_location", [
        "2024-5/DiccionarioHogar.zip", "2024-5/DiccionarioIndividual.zip", "2024-5/DiccionarioSalud.zip"]),
    "Encuesta Nacional de Programas Presupuestales - ENAPRES": ("enapres", "household_location", [
        "2024-18/02_Cuestionario_01A.zip", "2024-18/03_Cuestionario_01B.zip"]),
    "EPEN \x96 DEPARTAMENTOS": ("epen", "household_location", ["2024-156/Diccionario.zip"]),
    "Registro Nacional de Municipalidades - RENAMU": ("renamu", "municipality_location", ["2024-142/Diccionario_Anexo01.zip"]),
    "ENCUESTA NACIONAL AGROPECUARIA": ("ena", "agricultural_unit_location", [
        "2024-62/01_CUESTIONARIO_ENA_2024.zip", "2024-62/02_CUESTIONARIO_EMPRESA_2024.zip"]),
}
LEVELS = ["department", "province", "district"]
HOUSEHOLD_TABLES = {"RECH1", "RECH4", "RECHM", "RECH23", "RECH5", "RECH6", "CSALUD01", "CSALUD08",
                    "Programas Sociales x Hogar", "PS_BECA18", "PS_COMEDOR", "PS_PENSION65", "PS_QALIWARMA",
                    "PS_TRABAJA", "PS_VL", "PS_WAWAWASI"}
INDIVIDUAL_TABLES = {"REC91", "RE223132", "REC21", "REC41", "REC94", "DIT", "REC42", "REC43", "REC95",
                     "RE516171", "RE758081", "REC82", "REC83", "REC84DV", "REC44", "REC93DVdisciplina"}


def csv_schema(archive, name):
    encoding = "utf-8-sig"
    try:
        decoder = codecs.getincrementaldecoder(encoding)()
        with archive.open(name) as stream:
            for data in iter(lambda: stream.read(1024 * 1024), b""):
                decoder.decode(data)
            decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        encoding = "latin-1"
    with archive.open(name) as stream:
        header = stream.readline().decode(encoding)
    delimiter = csv.Sniffer().sniff(header, delimiters=",;\t").delimiter
    columns = next(csv.reader([header], delimiter=delimiter))
    if len(columns) != len(set(c.lower() for c in columns)):
        raise ValueError(f"Ambiguous columns in {name}")
    return encoding, delimiter, columns


def table_rule(family, name, columns):
    names = {c.lower(): c for c in columns}
    stem = Path(name).stem.removesuffix("_2024")
    if family in {"enaho", "endes", "renamu"} and "ubigeo" in names:
        return {"method": "ubigeo", "columns": [names["ubigeo"]], "levels": LEVELS}
    if family in {"enapres", "ena", "renamu"} and all(c in names for c in ("ccdd", "ccpp", "ccdi")):
        return {"method": "components", "columns": [names[c] for c in ("ccdd", "ccpp", "ccdi")], "levels": LEVELS}
    if family == "epen" and "ccdd" in names:
        return {"method": "department", "columns": [names["ccdd"]], "levels": LEVELS[:1]}
    if family == "endes":
        if stem in HOUSEHOLD_TABLES and "hhid" in names:
            return {"method": "join", "columns": [names["hhid"]], "levels": LEVELS,
                    "parent_code": "968-Modulo1629", "parent_table": "RECH0_2024.csv", "parent_key": "HHID"}
        if stem in INDIVIDUAL_TABLES and "caseid" in names:
            return {"method": "join", "columns": [names["caseid"]], "levels": LEVELS,
                    "parent_code": "968-Modulo1631", "parent_table": "REC0111_2024.csv", "parent_key": "CASEID"}
    return {"method": "unsupported", "columns": [], "levels": [],
            "reason": "Reference table" if family == "enaho" and stem.upper().startswith("ENAHO-TABLA-")
            else "No verified geographic field or relationship"}


def build(data_dir):
    records = []
    for entry in load_catalog():
        if entry["value"] not in RULES:
            continue
        family, meaning, sources = RULES[entry["value"]]
        for period, data in entry["years"].get("2024", {}).items():
            for mod in data["modules"]:
                code = mod.get("csv_code")
                if not code:
                    continue
                tables = []
                with zipfile.ZipFile(data_dir / (code + ".zip")) as archive:
                    for name in archive.namelist():
                        if not name.lower().endswith(".csv"):
                            continue
                        encoding, delimiter, columns = csv_schema(archive, name)
                        rule = table_rule(family, name, columns)
                        tables.append(dict(rule, path=name, encoding=encoding, delimiter=delimiter,
                                           text_columns=[c for c in columns if c.lower() in
                                                         {"ubigeo", "ccdd", "ccpp", "ccdi", "hhid", "caseid",
                                                          "conglome", "conglomerado", "vivienda", "hogar", "id_prod", "ua"}]))
                if not tables:
                    raise ValueError(f"No CSV tables in {code}")
                if len({Path(t['path']).name for t in tables}) != len(tables):
                    raise ValueError(f"Duplicate output filenames in {code}")
                records.append({"survey_value": entry["value"], "year": "2024", "period": period,
                                "archive_code": code, "meaning": meaning,
                                "sources": [DOC + s for s in sources], "tables": tables})
    return {"version": 1, "records": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] /
                        "src/inei_microdatos/data/survey_geography.json")
    args = parser.parse_args()
    result = build(args.data_dir)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Audited {len(result['records'])} modules")
