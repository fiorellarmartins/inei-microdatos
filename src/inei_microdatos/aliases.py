"""Short aliases for survey names."""

from __future__ import annotations

# Maps short alias -> substring that matches the survey label.
# The alias is matched case-insensitively against the catalog filter.
ALIASES = {
    # Household surveys
    "enaho":        "Condiciones de Vida y Pobreza - ENAHO",
    "enaho-panel":  "ENAHO PANEL",
    "enaho-empleo": "Empleo e Ingreso - ENAHO",

    # Demographic & health
    "endes":        "Demográfica y de Salud Familiar - ENDES",

    # Employment
    "epen":         "EPEN",
    "epe":          "EPE",
    "epe-lima":     "EPE  LIMA METROPOLITANA",
    "epen-ciudades":"EPEN  CIUDADES",
    "epen-deptos":  "EPEN  DEPARTAMENTOS",

    # Censuses
    "cenagro":      "CENSO NACIONAL AGROPECUARIO - CENAGRO",
    "cenama":       "CENSO NACIONAL DE MERCADOS DE ABASTOS",
    "censo-edu":    "CENSO DE INFRAESTRUCTURA EDUCATIVA",
    "censo-univ":   "CENSO NACIONAL UNIVERSITARIO",
    "censo-econ":   "CENSO NACIONAL ECONÓMICO",
    "censo-comis":  "CENSO NACIONAL DE COMISARIAS",
    "censo-penit":  "CENSO NACIONAL DE POBLACIÓN PENITENCIARIA",

    # Economic surveys
    "eea":          "ENCUESTA ECONÓMICA ANUAL - EEA",
    "emype":        "ENCUESTA DE MICRO Y PEQUEÑA EMPRESA",
    "ena":          "ENCUESTA NACIONAL AGROPECUARIA",
    "empresas":     "ENCUESTA NACIONAL DE EMPRESAS",

    # Social / programmatic
    "enapres":      "ENCUESTA NACIONAL DE PROGRAMAS PRESUPUESTALES",
    "enapref":      "ENCUESTA NACIONAL DE PRESUPUESTOS FAMILIARES",
    "enares":       "ENCUESTA NACIONAL SOBRE RELACIONES SOCIALES",
    "enco":         "ENCUESTA NACIONAL CONTINUA",
    "enpove":       "ENCUESTA DIRIGIDA A LA POBLACIÓN VENEZOLANA",
    "ensusalud":    "SATISFACCIÓN DE USUARIOS EN SALUD",
    "enut":         "ENCUESTA NACIONAL DE USO DEL TIEMPO",
    "eti":          "TRABAJO INFANTIL",
    "enedis":       "DISCAPACIDAD - ENEDIS",
    "enl":          "ENCUESTA NACIONAL DE LECTURA",

    # Health facility surveys
    "encred":       "ESTABLECIMIENTOS DE SALUD",
    "fonb":         "FUNCIONES OBSTÉTRICAS",

    # Municipality / local
    "renamu":       "REGISTRO NACIONAL DE MUNICIPALIDADES - RENAMU",
    "renamu-cp":    "DIRECTORIO NACIONAL DE MUNICIPALIDADES DE CENTROS POBLADOS",

    # Other
    "covid":        "COVID-19 EN LAS EMPRESAS",
    "lgbti":        "LGBTI",
    "tbc":          "TUBERCULOSIS",
    "pobreza":      "MAPA DE POBREZA",
    "pobreza-multi":"POBREZA MULTIDIMENSIONAL",
    "victimizacion":"VICTIMIZACIÓN",
    "nacimientos":  "ESTADÍSTICAS VITALES",
    "enaprom":      "ENAPROM",
    "habilidades":  "HABILIDADES AL TRABAJO",
    "innovacion":   "INNOVACIÓN EN LA INDUSTRIA",
    "denuncias":    "DENUNCIAS DE DELITOS",
    "cenan":        "MEDICIONES ANTROPOMÉTRICAS",
    "venezolanos":  "POBLACIÓN VENEZOLANA",
    "nutricion":    "COMPOSICIÓN NUTRICIONAL",
    "rural":        "ENCUESTA PROVINCIAL A HOGARES RURALES",
    "vulnerabilidad":"VULNERABILIDAD ECONÓMICA",
    "egresados":    "EGRESADOS UNIVERSITARIOS",
    "inst-edu":     "INSTITUCIONES EDUCATIVAS",
}


def resolve_alias(name: str) -> str:
    """Resolve a short alias to a survey filter substring.

    If the name is a known alias, returns the full filter string.
    Otherwise returns the input unchanged (it's used as a substring filter).
    """
    return ALIASES.get(name.lower(), name)


def list_aliases() -> dict:
    """Return all known aliases."""
    return dict(ALIASES)
