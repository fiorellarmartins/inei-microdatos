# inei-microdatos

Acceso programático al [portal de microdatos del INEI](https://proyectos.inei.gob.pe/microdatos/). Descarga microdatos de encuestas, censos y documentación sin navegar los dropdowns del portal.

El portal alberga **67 encuestas**, **5,900+ módulos descargables** y **8,100+ archivos de documentación** desde 1994 hasta 2025 — incluyendo encuestas de hogares (ENAHO), encuestas demográficas y de salud (ENDES), encuestas de empleo (EPEN), censos agropecuarios (CENAGRO), encuestas económicas (EEA) y decenas más.

[English version below](#english)

---

## El problema

El portal de microdatos del INEI es una aplicación ASP antigua con dropdowns en cascada vía AJAX. No hay API. Descargar un solo módulo requiere 4 clicks. Descargar una encuesta completa a través de los años requiere cientos. El portal usa codificación Windows-1252 con secuencias de escape estilo JavaScript que rompen los clientes HTTP estándar.

Este paquete maneja todo eso.

## Instalación

```bash
pip install inei-microdatos
```

Requiere Python 3.8+. Para leer datos en DataFrames, también necesitas pandas:

```bash
pip install inei-microdatos pandas
```

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
print(catalog_age())  # "2026-03-31T16:00:31+00:00"

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

Programmatic access to Peru's [INEI microdata portal](https://proyectos.inei.gob.pe/microdatos/). Download survey microdata, census files, and documentation without clicking through the portal's dropdowns.

The portal hosts **67 surveys**, **5,900+ downloadable modules**, and **8,100+ documentation files** spanning from 1994 to 2025 — covering household surveys (ENAHO), demographic and health surveys (ENDES), employment surveys (EPEN), agricultural censuses (CENAGRO), economic surveys (EEA), and dozens more.

## The problem

INEI's microdata portal is an old ASP application with cascading AJAX dropdowns. There is no API. Downloading a single module requires 4 clicks. Downloading an entire survey across years requires hundreds. The portal uses Windows-1252 encoding with JavaScript-style escape sequences that break standard HTTP clients.

This package handles all of that.

## Install

```bash
pip install inei-microdatos
```

Requires Python 3.8+. For reading data into DataFrames, you'll also need pandas:

```bash
pip install inei-microdatos pandas
```

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
print(catalog_age())  # "2026-03-31T16:00:31+00:00"

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
