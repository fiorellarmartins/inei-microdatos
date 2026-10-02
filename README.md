# inei-microdatos

[![PyPI](https://img.shields.io/pypi/v/inei-microdatos)](https://pypi.org/project/inei-microdatos/)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/inei-microdatos)](https://pypi.org/project/inei-microdatos/)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=ko-fi)](https://ko-fi.com/fiorellarmartins)

Acceso programático al [portal de microdatos del INEI](https://proyectos.inei.gob.pe/microdatos/). Descarga microdatos de encuestas, censos y documentación sin navegar los dropdowns del portal.

El portal alberga **67 encuestas**, **5,900+ módulos descargables** y **8,100+ archivos de documentación** desde 1994 hasta 2025 — incluyendo encuestas de hogares (ENAHO), encuestas demográficas y de salud (ENDES), encuestas de empleo (EPEN), censos agropecuarios (CENAGRO), encuestas económicas (EEA) y decenas más.

Incluye un **índice de variables** pre-construido con **551,000+ variables** de 3,700+ módulos que permite buscar variables por nombre o descripción sin descargar datos.

[English version below](#english)

---

## El problema

El portal de microdatos del INEI es una aplicación ASP antigua con dropdowns en cascada vía AJAX. No hay API. Descargar un solo módulo requiere 4 clicks. Descargar una encuesta completa a través de los años requiere cientos. El portal usa codificación Windows-1252 con secuencias de escape estilo JavaScript que rompen los clientes HTTP estándar.

Este paquete maneja todo eso.

## Instalación

```bash
pip install inei-microdatos
```

Requiere Python 3.9+. Incluye pandas, pyreadstat y openpyxl para leer CSV, STATA, SPSS y XLSX.

## Inicio rápido

```python
from inei_microdatos import load_catalog, download_modules, read_module
from inei_microdatos.catalog import filter_catalog

# Cargar el catálogo incluido (viene con el paquete, sin configuración)
catalog = load_catalog()

# Filtrar lo que necesitas
endes_2024 = filter_catalog(catalog, survey="endes", year_min=2024)

# Descargar
download_modules(endes_2024, dest="./data/", fmt="CSV", workers=4)

# Leer en DataFrames
dfs = read_module("./data/ENDES/2024/Unico/968-Modulo1629.zip")
for name, df in dfs.items():
    print(f"{name}: {df.shape}")
# RECH0: (37390, 44)
# RECH1: (135045, 36)
# RECH4: (135045, 22)
# RECHM: (3002, 8)
```

## Censos de Población y Vivienda

Un solo dataset, con la misma jerarquía del resto del catálogo:
**censo → año → periodo `Unico` → módulos**. Usa `censo`, `cpv` o
`censo-poblacion`. Los alias por año (`censo2017`, `cpv2025`, etc.) filtran esa
misma entrada; no crean datasets duplicados.

| Año | Acceso incluido | Formato |
|-----|-----------------|---------|
| 1981 | 87 frecuencias nacionales de REDATAM, generadas al descargar | XLS (SYLK) |
| 1993 | 76 frecuencias nacionales de REDATAM, generadas al descargar | XLS (SYLK) |
| 2005 | 27 frecuencias nacionales de REDATAM, generadas al descargar | XLS (SYLK) |
| 2007 | 103 cuadros descubiertos en el índice temático, selección nacional | XLS (tablas HTML servidas por INEI como Excel) |
| 2017 | 5 tomos nacionales de resultados definitivos | XLSX |
| 2025 | 11 libros nacionales de población, hogares y viviendas | XLSX |

Fuentes: [directorio de censos](https://www.inei.gob.pe/estadisticas/censos/),
[REDATAM 1981](http://censos1.inei.gob.pe/censos1981/redatam/),
[REDATAM 1993](http://censos1.inei.gob.pe/censos1993/redatam/),
[REDATAM 2005](http://censos1.inei.gob.pe/Censos2005/redatam/),
[tabulados 2007](https://censos.inei.gob.pe/cpv2007/tabulados/),
[resultados 2017](https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1544/),
[tabulados 2025](https://censos2025.inei.gob.pe/resultados/descarga-de-datos/cuadros-estadisticos/tabulados).

```bash
inei-microdatos list --survey censo
inei-microdatos list --survey censo --year-min 2017 --period Unico
inei-microdatos download --survey censo --year-min 2017 --format XLSX --dest ./data/
inei-microdatos download --survey censo2007 --format XLS --dest ./data/
inei-microdatos download --survey censo1993 --format XLS --dest ./data/
inei-microdatos read "./data/CENSOS NACIONALES DE POBLACIÓN Y VIVIENDA/2017/Unico/CPV2017-00-tomo-01.xlsx" --info
```

Son **tabulados agregados**, no microdatos. `Unico` significa una ronda censal,
no una encuesta anual. La estructura del catálogo es uniforme, pero las tablas,
definiciones y geografías originales pueden cambiar entre censos; no se unen
ni se armonizan sus filas. No se incluyen muestras de IPUMS ni descargas de libros
regionales.

Para 1981, 1993 y 2005, cada módulo es la frecuencia nacional de una variable
del formulario oficial de población, hogar o vivienda. La descarga ejecuta la
consulta, sigue el enlace temporal y guarda el Excel original de INEI (contenido
SYLK con extensión `.xls`). El catálogo conserva los parámetros, no los enlaces
temporales. Las consultas se ejecutan secuencialmente y los archivos válidos se
reutilizan. Se conservan los pesos del formulario, incluido `PERSONA.FACTEXP`
en 1981, y la cobertura de la base consultada; no se ajustan sus totales.
Este soporte requiere que el servidor REDATAM esté disponible; no incluye
cruces personalizados, selección regional ni extracción de registros individuales.

`download_modules()`, `read_module()` y `read_catalog_entry()` usan la misma API
que los otros datasets. Para XLSX, cada hoja conserva todas sus filas
(`header=None`); para XLS 2007, la tabla `tabDetalle` conserva sus encabezados.
Los XLS de REDATAM se leen como `REDATAM`, conservando títulos, filas vacías y notas.
`--table` permite seleccionar una hoja o tabla. La búsqueda incluida cubre las
variables de origen REDATAM y los títulos de los tabulados, identificando cada
resultado como variable o tabla. Los archivos conservan `.xlsx` o `.xls`
con cualquier layout. Con fallback activado, CSV puede descargar el Excel
original; no se convierte a CSV. Usa `--no-fallback` para exigir el formato.

Un catálogo local anterior tiene prioridad sobre el incluido. Puedes crear uno
separado actualizado sin reemplazarlo:

```bash
inei-microdatos crawl --survey censo --catalog ./censo.json --refresh
inei-microdatos download --catalog ./censo.json --survey censo2017 --format XLSX --dest ./data/
```

El índice incluido cubre los 309 módulos censales: **190 variables REDATAM**
(1981: 87; 1993: 76; 2005: 27) y **281 tablas** (2007: 103; 2017: 83; 2025: 95).
Las tablas se buscan por su título oficial y nombre de hoja; no se presentan
como columnas de microdatos ni se indexan sus cifras, notas o anexos.

```bash
inei-microdatos search sexo --survey censo
inei-microdatos search agua --survey censo2025
inei-microdatos search PERSONA.SEXO --survey censo1981 --exact
inei-microdatos index --survey censo --data-dir ./data/
```

La búsqueda funciona sin conexión con el índice incluido. La reconstrucción
usa el catálogo para los códigos y etiquetas REDATAM y los títulos de 2007;
descarga los 16 libros XLSX de 2017/2025 o reutiliza los archivos de `--data-dir`.
Los resultados de Python incluyen `kind` (`variable` o `table`), `data_kind`,
`module_code`, `table` (hoja para lectura, cuando corresponde) y `source_url`.
`track` compara únicamente códigos de variables exactos; no armoniza los códigos
entre censos ni compara nombres de tablas.

Para actualizar el catálogo incluido: `python scripts/update_census.py`.
Para reconstruir el índice censal incluido: `python scripts/update_census_index.py`
(opcionalmente `--data-dir ./data/`). El script conserva el índice de encuestas y
rechaza una reconstrucción incompleta.

## Búsqueda de variables

El paquete incluye un índice pre-construido con **551,000+ variables** de 16 encuestas principales, además de variables y tablas de los seis censos de población y vivienda. Busca por nombre o descripción sin descargar nada.

### CLI

```bash
# Buscar por nombre o descripción
inei-microdatos search ingreso
inei-microdatos search "material predominante"
inei-microdatos search p21 --exact

# Filtrar por encuesta o año
inei-microdatos search pobreza --survey enaho
inei-microdatos search CIIU --survey eea --year 2024

# Rastrear una variable a través de los años
inei-microdatos track p21 --survey enaho
inei-microdatos track ubigeo
```

### Python

```python
from inei_microdatos import search_variables, search_across_years

# Buscar variables
results = search_variables("ingreso")
for r in results[:5]:
    print(f'{r["variable"]:<20} {r["label"]:<50} {r["year"]}')

# Rastrear cambios a través de los años
by_year = search_across_years("p21", survey="enaho")
for year, matches in by_year.items():
    print(f'{year}: {matches[0]["label"][:60]}')
```

### Encuestas indexadas

| Encuesta | Módulos | Variables | Años |
|----------|---------|-----------|------|
| ENAHO | 730 | 90,000+ | 2004-2025 |
| ENAHO PANEL | 68 | 154,000+ | 2010-2024 |
| EEA | 604 | 9,000+ | 2001-2024 |
| EPEN (Ciudades/Deptos/Lima) | 892 | 108,000+ | 2001-2026 |
| ENDES | 264 | 27,000+ | 1996-2024 |
| Instituciones Educativas | 286 | 75,000+ | 2009-2021 |
| ENAPRES | 204 | 35,000+ | 2010-2024 |
| CENAGRO | 291 | 12,000+ | 2012 |
| Agropecuaria | 220 | 14,000+ | 2014-2024 |
| RENAMU | 75 | 10,000+ | 2004-2025 |
| MAPA DE POBREZA | 92 | 18,000+ | 2013 |

Para indexar encuestas adicionales:

```bash
inei-microdatos index --survey endes --workers 6
```

## Aliases de encuestas

En lugar de escribir nombres completos, usa aliases cortos:

```bash
inei-microdatos list --survey enaho     # en vez de "Condiciones de Vida y Pobreza - ENAHO"
inei-microdatos list --survey endes     # en vez de "Demográfica y de Salud Familiar - ENDES"
inei-microdatos list --survey cenagro   # en vez de "CENSO NACIONAL AGROPECUARIO - CENAGRO"
```

Aliases comunes: `enaho`, `endes`, `epen`, `epe-lima`, `cenagro`, `eea`, `enapres`, `renamu`, `enaho-panel`, `enpove`, `enapref`, `enares`, `lgbti` y [50+ más](src/inei_microdatos/aliases.py). Ejecuta `inei-microdatos aliases` para ver todos.

Los aliases funcionan en todos los lugares donde se acepta `--survey` — en el CLI y en `filter_catalog()`.

## CLI

El paquete incluye una interfaz de línea de comandos para explorar y descargar sin escribir código.

### Explorar datos disponibles

```bash
# Resumen general
inei-microdatos stats

# Listar todas las encuestas
inei-microdatos list

# Filtrar
inei-microdatos list --survey enaho --year-min 2020
inei-microdatos list --survey endes
inei-microdatos list --survey cenagro
```

### Descargar

```bash
# Descargar ENDES 2020-2024 como CSV
inei-microdatos download --survey endes --year-min 2020 --format CSV --dest ./data/

# Descargar ENAHO anual como STATA
inei-microdatos download --survey enaho --period "Anual" --year-min 2018 --format STATA --dest ./data/

# Incluir documentación (cuestionarios, diccionarios, fichas técnicas)
inei-microdatos download --survey enaho --year-min 2024 --format CSV --dest ./data/ --include-docs

# Descargar solo documentación
inei-microdatos docs --survey endes --year-min 2020 --dest ./docs/

# Vista previa de lo que se descargaría (sin descargar)
inei-microdatos download --survey endes --year-min 2024 --format CSV --dest ./data/ --dry-run
```

### Leer archivos descargados

```bash
# Listar tablas dentro de un ZIP
inei-microdatos read ./data/968-Modulo1629.zip --info

# Vista previa de datos
inei-microdatos read ./data/968-Modulo1629.zip -t RECH0
```

### Organización de carpetas

Controla cómo se organizan los archivos en disco:

```bash
# Por defecto: {survey}/{year}/{period}/{code}.zip
inei-microdatos download --survey endes --dest ./data/

# Plano por año (sin subcarpetas de período)
inei-microdatos download --survey endes --dest ./data/ --layout by-year

# Completamente plano
inei-microdatos download --survey endes --dest ./data/ --layout flat

# Organizado por formato
inei-microdatos download --survey endes --dest ./data/ --layout by-format

# Template personalizado
inei-microdatos download --survey endes --dest ./data/ \
  --layout "{year}/{survey}/{module_name}.zip"
```

Placeholders disponibles: `{survey}`, `{year}`, `{period}`, `{code}`, `{module_name}`, `{format}`.

## API de Python

### Catálogo

```python
from inei_microdatos import load_catalog
from inei_microdatos.catalog import filter_catalog, catalog_stats, catalog_age

# Cargar catálogo incluido (sin configuración)
catalog = load_catalog()

# Verificar cuándo se generó
print(catalog_age())  # "2026-05-19T13:36:51+00:00"

# Estadísticas
print(catalog_stats(catalog))
# {'surveys': 67, 'survey_years': 295, 'modules': 5932, ...}

# Filtrar por nombre de encuesta (o alias), rango de años, período
enaho = filter_catalog(catalog, survey="enaho", year_min=2020, period="Anual")
```

### Descarga

```python
from inei_microdatos import download_modules, download_docs

# Descargar con fallback de formato (CSV preferido, cae a STATA/SPSS si no hay)
result = download_modules(catalog, dest="./data/", fmt="CSV", workers=4)
# {'ok': 13, 'skipped': 0, 'failed': 0, 'bad_zip': 0}

# Formato estricto (sin fallback)
result = download_modules(catalog, dest="./data/", fmt="STATA", fallback=False)

# Vista previa sin descargar
result = download_modules(catalog, dest="./data/", fmt="CSV", dry_run=True)

# Documentación
result = download_docs(catalog, dest="./docs/", workers=4)
```

### Lectura

```python
from inei_microdatos import read_module, read_catalog_entry, list_tables

# Desde un ZIP descargado
dfs = read_module("./data/968-Modulo1629.zip")

# Leer solo tablas específicas
dfs = read_module("./data/968-Modulo1629.zip", tables=["RECH0", "RECH1"])

# Desde un código de descarga (descarga a directorio temporal automáticamente)
dfs = read_module("968-Modulo1629")

# Directo desde catálogo (descarga + lee en un paso)
dfs = read_catalog_entry(catalog[0], year="2024", module="Hogar")

# Inspeccionar sin leer
tables = list_tables("./data/968-Modulo1629.zip")
# [{'name': 'RECH0', 'format': 'csv', 'size_bytes': 6598376, ...}, ...]
```

### Búsqueda de variables

```python
from inei_microdatos import search_variables, search_across_years

# Buscar por nombre o descripción
results = search_variables("ingreso")
# [{'survey': '...', 'year': '2024', 'variable': 'p21', 'label': '...', ...}, ...]

# Búsqueda exacta por nombre de variable
results = search_variables("p21", exact=True)

# Filtrar por encuesta
results = search_variables("pobreza", survey="enaho")

# Rastrear una variable a través de los años
by_year = search_across_years("ubigeo")
# {'2004': [...], '2005': [...], ..., '2024': [...]}
```

### Cliente (bajo nivel)

```python
from inei_microdatos import INEIClient

client = INEIClient()
surveys = client.get_surveys()
years = client.get_years(surveys[0])
periods = client.get_periods(surveys[0], years[0])
modules = client.get_modules(surveys[0], years[0], periods[0])

print(modules[0].download_url("STATA"))
# https://proyectos.inei.gob.pe/iinei/srienaho/descarga/STATA/966-Modulo01.zip
```

### Actualizar el catálogo

El catálogo incluido es una foto fija. Para obtener los datos más recientes del INEI:

```python
from inei_microdatos import INEIClient
from inei_microdatos.catalog import build_catalog, save_catalog

client = INEIClient()
catalog = build_catalog(client)  # ~10 minutos
save_catalog(catalog, "~/.inei-microdatos/catalog.json")
```

O por CLI:

```bash
inei-microdatos crawl                    # primera vez
inei-microdatos crawl --refresh          # re-crawl
inei-microdatos crawl --survey enaho     # solo una encuesta específica
```

## Formatos disponibles

| Formato | Cobertura | Notas |
|---------|-----------|-------|
| **SPSS** (.sav) | ~98% de los módulos | Mayor cobertura |
| **STATA** (.dta) | ~42% | Incluye etiquetas de valores |
| **CSV** | ~43% | UTF-8 con BOM |
| **XLSX** | Censos 2017 y 2025 | Tabulados agregados nacionales |
| **XLS** | Censo 2007 | Exportaciones HTML de INEI |

Las encuestas antiguas (pre-2008) frecuentemente solo están disponibles en SPSS/STATA, no en CSV. El flag `--format CSV` automáticamente cae a STATA o SPSS cuando CSV no está disponible. Usa `--no-fallback` para desactivar esto.

## Separación metodológica de ENAHO

ENAHO cambió de metodología en 2004. El portal del INEI ofrece "ENAHO Metodología Anterior" y "ENAHO Metodología Actualizada" como dropdowns separados, pero devuelven datos idénticos para la encuesta principal "Condiciones de Vida y Pobreza".

Este paquete automáticamente los separa en el límite metodológico:
- **ENAHO Anterior**: 1997–2003 (metodología antigua)
- **ENAHO Actualizada**: 2004–presente (metodología actual)

Las sub-encuestas temáticas (Empleo, Educación, Victimización, etc.) y las variantes PANEL son datasets genuinamente distintos y se preservan tal cual.

## Cómo funciona

El portal del INEI usa tres endpoints AJAX detrás de dropdowns en cascada:

1. `CambiaEnc.asp` — selección de encuesta, devuelve años disponibles
2. `CambiaAnio.asp` — selección de año, devuelve períodos disponibles
3. `cambiaPeriodo.asp` — selección de período, devuelve tabla de módulos con links de descarga

Las URLs de descarga siguen un patrón predecible: `https://proyectos.inei.gob.pe/iinei/srienaho/descarga/{FORMATO}/{CÓDIGO}.zip`

El detalle crítico de implementación es la codificación: los nombres de encuestas que contienen caracteres Windows-1252 (como el en-dash `\x96` en los nombres de encuestas EPEN) deben codificarse usando la convención `escape()` de JavaScript (`%96`), no la codificación percent UTF-8 por defecto de Python (`%C2%96`). La codificación de formularios estándar de `requests` falla silenciosamente — el servidor devuelve HTML vacío sin error.

## Licencia

MIT

---

<a name="english"></a>

# inei-microdatos (English)

[![PyPI](https://img.shields.io/pypi/v/inei-microdatos)](https://pypi.org/project/inei-microdatos/)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/inei-microdatos)](https://pypi.org/project/inei-microdatos/)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=ko-fi)](https://ko-fi.com/fiorellarmartins)

Programmatic access to Peru's [INEI microdata portal](https://proyectos.inei.gob.pe/microdatos/). Download survey microdata, census files, and documentation without clicking through the portal's dropdowns.

The portal hosts **67 surveys**, **5,900+ downloadable modules**, and **8,100+ documentation files** spanning from 1994 to 2025 — covering household surveys (ENAHO), demographic and health surveys (ENDES), employment surveys (EPEN), agricultural censuses (CENAGRO), economic surveys (EEA), and dozens more.

Includes a **pre-built variable index** with **551,000+ variables** from 3,700+ modules for searching variables by name or description without downloading data.

## The problem

INEI's microdata portal is an old ASP application with cascading AJAX dropdowns. There is no API. Downloading a single module requires 4 clicks. Downloading an entire survey across years requires hundreds. The portal uses Windows-1252 encoding with JavaScript-style escape sequences that break standard HTTP clients.

This package handles all of that.

## Install

```bash
pip install inei-microdatos
```

Requires Python 3.9+. Includes pandas, pyreadstat, and openpyxl to read CSV, STATA, SPSS, and XLSX.

## Quick start

```python
from inei_microdatos import load_catalog, download_modules, read_module
from inei_microdatos.catalog import filter_catalog

# Load the bundled catalog (ships with the package, no setup needed)
catalog = load_catalog()

# Filter to what you need
endes_2024 = filter_catalog(catalog, survey="endes", year_min=2024)

# Download
download_modules(endes_2024, dest="./data/", fmt="CSV", workers=4)

# Read into DataFrames
dfs = read_module("./data/ENDES/2024/Unico/968-Modulo1629.zip")
for name, df in dfs.items():
    print(f"{name}: {df.shape}")
# RECH0: (37390, 44)
# RECH1: (135045, 36)
# RECH4: (135045, 22)
# RECHM: (3002, 8)
```

## Population and Housing Censuses

One dataset, using the catalog's existing hierarchy:
**censo → year → `Unico` period → modules**. Use `censo`, `cpv`, or
`censo-poblacion`. Year-specific aliases (`censo2017`, `cpv2025`, etc.) filter
that same entry rather than creating duplicate datasets.

| Year | Included access | Format |
|------|-----------------|--------|
| 1981 | 87 national REDATAM frequencies, generated at download time | XLS (SYLK) |
| 1993 | 76 national REDATAM frequencies, generated at download time | XLS (SYLK) |
| 2005 | 27 national REDATAM frequencies, generated at download time | XLS (SYLK) |
| 2007 | 103 tables discovered in the thematic index, national selection | XLS (HTML tables served by INEI as Excel) |
| 2017 | 5 national volumes of final results | XLSX |
| 2025 | 11 national population, household, and housing workbooks | XLSX |

Sources: [census directory](https://www.inei.gob.pe/estadisticas/censos/),
[REDATAM 1981](http://censos1.inei.gob.pe/censos1981/redatam/),
[REDATAM 1993](http://censos1.inei.gob.pe/censos1993/redatam/),
[REDATAM 2005](http://censos1.inei.gob.pe/Censos2005/redatam/),
[2007 tables](https://censos.inei.gob.pe/cpv2007/tabulados/),
[2017 results](https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1544/),
[2025 tables](https://censos2025.inei.gob.pe/resultados/descarga-de-datos/cuadros-estadisticos/tabulados).

```bash
inei-microdatos list --survey censo
inei-microdatos list --survey censo --year-min 2017 --period Unico
inei-microdatos download --survey censo --year-min 2017 --format XLSX --dest ./data/
inei-microdatos download --survey censo2007 --format XLS --dest ./data/
inei-microdatos download --survey censo1993 --format XLS --dest ./data/
inei-microdatos read "./data/CENSOS NACIONALES DE POBLACIÓN Y VIVIENDA/2017/Unico/CPV2017-00-tomo-01.xlsx" --info
```

These are **aggregated tables**, not microdata. `Unico` denotes one census round,
not an annual survey. The catalog hierarchy is consistent, but original tables,
definitions, and geographies may differ across censuses; rows are not combined or
harmonized. IPUMS samples and regional-workbook downloads are not included.

For 1981, 1993, and 2005, each module is a national frequency table for one
variable from the official population, household, or housing form. Downloading
runs the query, follows its temporary link, and saves INEI's original Excel
export (SYLK content with an `.xls` extension). The catalog stores query
parameters, not temporary URLs. Queries run sequentially and valid local files
are reused. Form weights, including `PERSONA.FACTEXP` in 1981, and the queried
database's coverage are preserved; totals are not adjusted. This requires a
working REDATAM server. Custom cross-tabulations, regional selections, and
individual-record extraction are not included.

`download_modules()`, `read_module()`, and `read_catalog_entry()` follow the same
API as other datasets. XLSX sheets retain all rows (`header=None`); 2007 XLS
exports retain the heading rows in `tabDetalle`. REDATAM XLS exports are read as
`REDATAM`, retaining titles, blank rows, and notes. Use `--table` to select a sheet
or table. The bundled search covers REDATAM source variables and published
table titles, identifying each result as a variable or table. All
layouts retain `.xlsx` or `.xls`. With fallback enabled, a CSV request may fetch
the original Excel file; no conversion takes place. Use `--no-fallback` to
require the requested format.

An older local catalog takes precedence over the bundled one. Refresh into a
separate file without replacing it:

```bash
inei-microdatos crawl --survey censo --catalog ./censo.json --refresh
inei-microdatos download --catalog ./censo.json --survey censo2017 --format XLSX --dest ./data/
```

The bundled index covers all 309 census modules: **190 REDATAM variables**
(1981: 87; 1993: 76; 2005: 27) and **281 tables** (2007: 103; 2017: 83; 2025: 95).
Tables are searchable by their official titles and worksheet names; they are
not represented as microdata columns. Figures, presentation notes, and annexes
are not indexed.

```bash
inei-microdatos search sexo --survey censo
inei-microdatos search agua --survey censo2025
inei-microdatos search PERSONA.SEXO --survey censo1981 --exact
inei-microdatos index --survey censo --data-dir ./data/
```

Search works offline with the bundled index. Rebuilding uses catalog metadata
for REDATAM codes/labels and 2007 titles; it downloads the 16 XLSX workbooks from
2017/2025 or reuses files under `--data-dir`. Python results include `kind`
(`variable` or `table`), `data_kind`, `module_code`, `table` (the worksheet to read,
where applicable), and `source_url`. `track` compares exact variable codes only;
it does not harmonize codes across census years or compare table names.

To refresh the bundled catalog: `python scripts/update_census.py`.
To rebuild the bundled census index: `python scripts/update_census_index.py`
(optionally `--data-dir ./data/`). The script preserves survey entries and
rejects an incomplete rebuild.

## Variable search

The package includes a pre-built index with **551,000+ variables** from 16 major surveys, plus variables and tables from all six population and housing censuses. Search by name or description without downloading anything.

### CLI

```bash
# Search by name or description
inei-microdatos search ingreso
inei-microdatos search "material predominante"
inei-microdatos search p21 --exact

# Filter by survey or year
inei-microdatos search pobreza --survey enaho
inei-microdatos search CIIU --survey eea --year 2024

# Track a variable across years
inei-microdatos track p21 --survey enaho
inei-microdatos track ubigeo
```

### Python

```python
from inei_microdatos import search_variables, search_across_years

# Search variables
results = search_variables("ingreso")
for r in results[:5]:
    print(f'{r["variable"]:<20} {r["label"]:<50} {r["year"]}')

# Track changes across years
by_year = search_across_years("p21", survey="enaho")
for year, matches in by_year.items():
    print(f'{year}: {matches[0]["label"][:60]}')
```

### Indexed surveys

| Survey | Modules | Variables | Years |
|--------|---------|-----------|-------|
| ENAHO | 730 | 90,000+ | 2004-2025 |
| ENAHO PANEL | 68 | 154,000+ | 2010-2024 |
| EEA | 604 | 9,000+ | 2001-2024 |
| EPEN (Cities/Departments/Lima) | 892 | 108,000+ | 2001-2026 |
| ENDES | 264 | 27,000+ | 1996-2024 |
| Educational Institutions | 286 | 75,000+ | 2009-2021 |
| ENAPRES | 204 | 35,000+ | 2010-2024 |
| CENAGRO | 291 | 12,000+ | 2012 |
| Agricultural Survey | 220 | 14,000+ | 2014-2024 |
| RENAMU | 75 | 10,000+ | 2004-2025 |
| Poverty Map | 92 | 18,000+ | 2013 |

To index additional surveys:

```bash
inei-microdatos index --survey endes --workers 6
```

## Survey aliases

Instead of typing full survey names, use short aliases:

```bash
inei-microdatos list --survey enaho     # instead of "Condiciones de Vida y Pobreza - ENAHO"
inei-microdatos list --survey endes     # instead of "Demográfica y de Salud Familiar - ENDES"
inei-microdatos list --survey cenagro   # instead of "CENSO NACIONAL AGROPECUARIO - CENAGRO"
```

Common aliases: `enaho`, `endes`, `epen`, `epe-lima`, `cenagro`, `eea`, `enapres`, `renamu`, `enaho-panel`, `enpove`, `enapref`, `enares`, `lgbti`, and [50+ more](src/inei_microdatos/aliases.py). Run `inei-microdatos aliases` to see all.

Aliases work everywhere `--survey` is accepted — in the CLI and in `filter_catalog()`.

## CLI

The package includes a command-line interface for browsing and downloading without writing code.

### Browse available data

```bash
# Overview
inei-microdatos stats

# List all surveys
inei-microdatos list

# Filter
inei-microdatos list --survey enaho --year-min 2020
inei-microdatos list --survey endes
inei-microdatos list --survey cenagro
```

### Download

```bash
# Download ENDES 2020-2024 as CSV
inei-microdatos download --survey endes --year-min 2020 --format CSV --dest ./data/

# Download ENAHO annual data as STATA
inei-microdatos download --survey enaho --period "Anual" --year-min 2018 --format STATA --dest ./data/

# Include documentation (questionnaires, dictionaries, fichas)
inei-microdatos download --survey enaho --year-min 2024 --format CSV --dest ./data/ --include-docs

# Download only documentation
inei-microdatos docs --survey endes --year-min 2020 --dest ./docs/

# Preview what would be downloaded (no actual download)
inei-microdatos download --survey endes --year-min 2024 --format CSV --dest ./data/ --dry-run
```

### Read downloaded files

```bash
# List tables inside a ZIP
inei-microdatos read ./data/968-Modulo1629.zip --info

# Preview data
inei-microdatos read ./data/968-Modulo1629.zip -t RECH0
```

### Folder layouts

Control how files are organized on disk:

```bash
# Default: {survey}/{year}/{period}/{code}.zip
inei-microdatos download --survey endes --dest ./data/

# Flat by year (no period subfolders)
inei-microdatos download --survey endes --dest ./data/ --layout by-year

# Completely flat
inei-microdatos download --survey endes --dest ./data/ --layout flat

# Organized by format
inei-microdatos download --survey endes --dest ./data/ --layout by-format

# Custom template
inei-microdatos download --survey endes --dest ./data/ \
  --layout "{year}/{survey}/{module_name}.zip"
```

Available placeholders: `{survey}`, `{year}`, `{period}`, `{code}`, `{module_name}`, `{format}`.

## Python API

### Catalog

```python
from inei_microdatos import load_catalog
from inei_microdatos.catalog import filter_catalog, catalog_stats, catalog_age

# Load bundled catalog (zero setup)
catalog = load_catalog()

# Check when it was crawled
print(catalog_age())  # "2026-05-19T13:36:51+00:00"

# Stats
print(catalog_stats(catalog))
# {'surveys': 67, 'survey_years': 295, 'modules': 5932, ...}

# Filter by survey name (or alias), year range, period
enaho = filter_catalog(catalog, survey="enaho", year_min=2020, period="Anual")
```

### Download

```python
from inei_microdatos import download_modules, download_docs

# Download with format fallback (CSV preferred, falls back to STATA/SPSS)
result = download_modules(catalog, dest="./data/", fmt="CSV", workers=4)
# {'ok': 13, 'skipped': 0, 'failed': 0, 'bad_zip': 0}

# Strict format (no fallback)
result = download_modules(catalog, dest="./data/", fmt="STATA", fallback=False)

# Dry run (preview without downloading)
result = download_modules(catalog, dest="./data/", fmt="CSV", dry_run=True)

# Documentation
result = download_docs(catalog, dest="./docs/", workers=4)
```

### Read

```python
from inei_microdatos import read_module, read_catalog_entry, list_tables

# From a downloaded ZIP
dfs = read_module("./data/968-Modulo1629.zip")

# Read specific tables only
dfs = read_module("./data/968-Modulo1629.zip", tables=["RECH0", "RECH1"])

# From a download code (downloads to temp dir automatically)
dfs = read_module("968-Modulo1629")

# Directly from catalog (downloads + reads in one step)
dfs = read_catalog_entry(catalog[0], year="2024", module="Hogar")

# Inspect without reading
tables = list_tables("./data/968-Modulo1629.zip")
# [{'name': 'RECH0', 'format': 'csv', 'size_bytes': 6598376, ...}, ...]
```

### Variable search

```python
from inei_microdatos import search_variables, search_across_years

# Search by name or description
results = search_variables("ingreso")
# [{'survey': '...', 'year': '2024', 'variable': 'p21', 'label': '...', ...}, ...]

# Exact match on variable name
results = search_variables("p21", exact=True)

# Filter by survey
results = search_variables("pobreza", survey="enaho")

# Track a variable across years
by_year = search_across_years("ubigeo")
# {'2004': [...], '2005': [...], ..., '2024': [...]}
```

### Client (low-level)

```python
from inei_microdatos import INEIClient

client = INEIClient()
surveys = client.get_surveys()
years = client.get_years(surveys[0])
periods = client.get_periods(surveys[0], years[0])
modules = client.get_modules(surveys[0], years[0], periods[0])

print(modules[0].download_url("STATA"))
# https://proyectos.inei.gob.pe/iinei/srienaho/descarga/STATA/966-Modulo01.zip
```

### Update the catalog

The bundled catalog is a snapshot. To get the latest data from INEI:

```python
from inei_microdatos import INEIClient
from inei_microdatos.catalog import build_catalog, save_catalog

client = INEIClient()
catalog = build_catalog(client)  # ~10 minutes
save_catalog(catalog, "~/.inei-microdatos/catalog.json")
```

Or via CLI:

```bash
inei-microdatos crawl                    # first time
inei-microdatos crawl --refresh          # re-crawl
inei-microdatos crawl --survey enaho     # crawl specific survey only
```

## Available formats

| Format | Coverage | Notes |
|--------|----------|-------|
| **SPSS** (.sav) | ~98% of modules | Best coverage |
| **STATA** (.dta) | ~42% | Value labels included |
| **CSV** | ~43% | UTF-8 with BOM |
| **XLSX** | Censos 2017 and 2025 | National aggregated tables |
| **XLS** | Censo 2007 | INEI HTML exports |

Older surveys (pre-2008) are often available only in SPSS/STATA, not CSV. The `--format CSV` flag automatically falls back to STATA or SPSS when CSV isn't available. Use `--no-fallback` to disable this.

## ENAHO methodology split

ENAHO changed methodology in 2004. The INEI portal offers both "ENAHO Metodología Anterior" and "ENAHO Metodología Actualizada" as separate dropdowns, but they return identical data for the main "Condiciones de Vida y Pobreza" survey.

This package automatically splits them at the boundary:
- **ENAHO Anterior**: 1997–2003 (old methodology)
- **ENAHO Actualizada**: 2004–present (current methodology)

The thematic sub-surveys (Empleo, Educación, Victimización, etc.) and PANEL variants are genuinely distinct datasets and are preserved as-is.

## How it works

The INEI portal uses three AJAX endpoints behind cascading dropdowns:

1. `CambiaEnc.asp` — survey selection, returns available years
2. `CambiaAnio.asp` — year selection, returns available periods
3. `cambiaPeriodo.asp` — period selection, returns module table with download links

Download URLs follow a predictable pattern: `https://proyectos.inei.gob.pe/iinei/srienaho/descarga/{FORMAT}/{CODE}.zip`

The critical implementation detail is encoding: survey names containing Windows-1252 characters (like the en-dash `\x96` in EPEN survey names) must be encoded using JavaScript's `escape()` convention (`%96`), not Python's default UTF-8 percent-encoding (`%C2%96`). Standard `requests` form encoding silently fails — the server returns empty HTML with no error.

## License

MIT
