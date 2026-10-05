# Selección geográfica / Geographic selection

## Español

Desde **0.5.0**, `--ubigeo` y `ubigeo=` comparten una interfaz para censos y
encuestas con adaptadores verificados. Usa una cadena de 2 dígitos para
departamento, 4 para provincia o 6 para distrito: `01`, `0101`, `010101`.
Sin este parámetro, las descargas y lecturas habituales siguen funcionando igual.

### Consultar la cobertura antes de descargar

```bash
inei-microdatos geography --survey endes --year-min 2024 --year-max 2024
inei-microdatos geography --survey epen-deptos --year-min 2024 --year-max 2024 --json
```

```python
from inei_microdatos import load_catalog, geography_capabilities
from inei_microdatos.catalog import filter_catalog

catalog = filter_catalog(load_catalog(), survey="endes", year_min=2024, year_max=2024)
coverage = geography_capabilities(catalog)
# También está disponible en cada módulo: module["geography_support"].
```

La consulta es local: informa encuesta, año, periodo, módulo, tabla, niveles,
método y fuentes. `verified` identifica reglas revisadas; `not_verified` significa
que todavía no hay un adaptador revisado para esa combinación, no que la encuesta
carezca de información geográfica. En los censos, `table_dependent` indica que
la disponibilidad depende del cuadro y del área solicitada.

### Cobertura inicial de encuestas

Se auditaron los CSV oficiales de **128 módulos de 2024**. No se extienden estas
reglas automáticamente a otros años, modalidades o archivos con nombres similares.

| Dataset | Periodos de 2024 | Selección | Ubicación representada |
|---|---|---|---|
| ENAHO | Anual y cuatro trimestres; excluye PANEL | Departamento, provincia, distrito mediante `UBIGEO` | Hogar |
| ENDES | Único | `UBIGEO` o relaciones verificadas mediante `HHID` y `CASEID` | Hogar de las personas encuestadas |
| ENAPRES | Anual | Departamento, provincia, distrito mediante `CCDD`, `CCPP`, `CCDI` | Hogar |
| EPEN Departamentos | Archivos nacional y departamentales del catálogo | Solo departamento mediante `CCDD` | Hogar |
| RENAMU | Anual | Departamento, provincia, distrito mediante `Ubigeo` | Municipalidad |
| ENA | Anual | Departamento, provincia, distrito mediante `CCDD`, `CCPP`, `CCDI`, en las tablas verificadas | Unidad agropecuaria |

Las tablas auxiliares de códigos de ENAHO se omiten. En ENA, `01_CAP100A_02.csv`
y `10_CAP400A_3.csv` no tienen un vínculo geográfico verificado y se omiten,
quedando identificadas en el reporte. El resto del catálogo se puede consultar
con el mismo comando, aunque su soporte todavía figure como `not_verified`.

Las fuentes revisadas son los diccionarios de ENAHO, ENDES, EPEN y RENAMU y los
cuestionarios de ENAPRES y ENA de 2024. Los enlaces oficiales específicos están en
`sources` del reporte de cobertura y del registro incluido en el paquete.

### Descargar y leer

```bash
inei-microdatos download --survey endes --year-min 2024 --year-max 2024 --ubigeo 150101 --dest ./data/
inei-microdatos download --survey enapres --year-min 2024 --year-max 2024 --ubigeo 01 --dest ./data/
inei-microdatos download --survey epen-deptos --year-min 2024 --year-max 2024 --ubigeo 15 --dest ./data/
```

```python
from inei_microdatos import download_modules, read_catalog_entry, select_geography

download_modules(catalog, "./data", ubigeo="150101")
frames = read_catalog_entry(catalog[0], "2024", module="Vivienda", dest="./cache", ubigeo="150101")
# El lector descarga automáticamente la tabla geográfica de apoyo de ENDES.
for frame in frames.values():
    print(frame.attrs["ubigeo"], frame.attrs["geography_report"]["status"])

# Alternativamente, reutiliza un catálogo seleccionado sin modificar el original:
selected = select_geography(catalog, "15")
download_modules(selected, "./data")
```

Para encuestas, primero se descarga el **ZIP CSV completo**; el filtrado es local,
por bloques, y produce un **ZIP derivado con CSV y `geography.json`**. La primera
descarga no ahorra transferencia. Los originales y las dependencias se guardan en
`.geography-sources/CSV/` y se reutilizan. Los subconjuntos se separan en
`ubigeo-<código>/`; con el layout predeterminado, el código también aparece en el
nombre del archivo. `read_catalog_entry()` usa el código en el nombre de su caché.

En esta versión, los subconjuntos de encuestas se exportan como CSV. Una preferencia
por STATA/SPSS usa fallback a CSV; con `--no-fallback`, se solicita elegir CSV.
Las descargas sin selección mantienen sus formatos originales. Se conservan las
columnas y los valores de los CSV fuente, incluidos pesos; no se recalculan
estimaciones ni se añaden etiquetas de STATA/SPSS. El lector conserva como texto
los campos geográficos y los identificadores registrados para mantener sus ceros.

La selección se aplica a la geografía publicada en cada archivo. No armoniza
límites entre años ni deduce ubicación de campos como lugar de nacimiento o
trabajo. Las relaciones de ENDES se limitan al mismo año/periodo y exigen claves
únicas en la tabla principal; filtrar una tabla hija no multiplica sus filas.

### Interpretar los resultados

- `ok`: subconjunto creado sin registros geográficamente indeterminados.
- `empty`: las tablas admiten la selección y no tienen observaciones coincidentes.
  Se conservan archivos con encabezados; esto no demuestra que el ubigeo no exista.
- `partial`: hay registros fuente sin ubicación resoluble o tablas de datos
  omitidas. Incluso un subconjunto vacío puede ser `partial`; no permite concluir
  que no haya observaciones del área entre los registros sin ubicación.
- `unavailable`: no hay soporte verificado para ese módulo/nivel. No descarga un
  sustituto nacional; `read_catalog_entry()` lanza `GeographyUnavailable`.
- `failed`: falló la fuente, cambió su esquema o una relación resultó ambigua.
- `skipped`: se reutilizó un archivo derivado existente con la misma selección y
  regla. Consulta su `geography.json` para conocer su estado original.

`geography.json` registra fuentes, selección, significado geográfico, filas fuente,
filas seleccionadas, filas sin ubicación y tablas omitidas. También aparece en
`DataFrame.attrs["geography_report"]`. Los originales permanecen intactos.
Filtrar una muestra por distrito no convierte sus estimaciones en representativas
de ese distrito: deben respetarse los dominios y el diseño muestral de cada encuesta.

El comportamiento de los censos se documenta en [la guía de censos](census.md).
La validación censal puede necesitar conexión; la consulta de capacidades y el
`--dry-run` de encuestas no descargan datos.

### Ampliar la cobertura

Revisa el diccionario/cuestionario del año y las claves de relación, incorpora
reglas explícitas en `scripts/update_survey_geography.py` y audita los ZIP CSV:

```bash
python scripts/update_survey_geography.py --data-dir ./official-csv-zips
```

El script genera `src/inei_microdatos/data/survey_geography.json` de forma
reproducible, verificando nombres de tablas, columnas, separadores y codificación.
El índice de variables sirve para descubrir candidatos; no habilita soporte por
sí solo. Agrega pruebas de ceros iniciales, relaciones, niveles no disponibles y
cambios de esquema, además de una comprobación con los archivos oficiales.

## English

Since **0.5.0**, `--ubigeo` / `ubigeo=` select departments (2 digits), provinces
(4), or districts (6) for verified datasets. Keep leading zeros, e.g. `010101`.
Omitting the argument preserves existing national downloads and readers.

Inspect coverage offline before downloading:

```bash
inei-microdatos geography --survey endes --year-min 2024 --year-max 2024 --json
inei-microdatos download --survey endes --year-min 2024 --year-max 2024 --ubigeo 150101 --dest ./data/
```

Python exposes `geography_capabilities(catalog)`, `select_geography(catalog, code)`,
`download_modules(..., ubigeo=code)`, and `read_catalog_entry(..., ubigeo=code)`.
Loaded catalog modules also expose `geography_support`, including table-level
coverage and links to reviewed official sources.

The initial registry audits **128 modules from 2024**: ENAHO annual and quarterly
(excluding PANEL), ENDES, ENAPRES, EPEN Departamentos, RENAMU, and ENA. EPEN supports
departments only. The others support all three levels in verified tables, using
full ubigeo codes, separate geographic components, or documented ENDES household
(`HHID`) / individual (`CASEID`) relationships within the same year and period.
ENAHO classification tables and two unverified ENA tables (`01_CAP100A_02.csv`,
`10_CAP400A_3.csv`) are omitted and listed in the report. RENAMU locates municipalities;
ENA locates agricultural units; the household surveys locate surveyed households.
Other years, variants, and datasets remain explicitly `not_verified`. This means
no reviewed adapter yet, not necessarily absence of public geographic information.

Survey selection downloads full source CSV ZIPs, then filters locally in chunks.
Derived ZIPs contain CSV tables and `geography.json`; originals and ENDES dependencies
are cached separately in `.geography-sources/CSV/`. Outputs use `ubigeo-<code>/`
directories, including custom layouts, and the default layout includes the code
in filenames. The reader's cache also includes the code in filenames.
Derived exports currently use CSV, falling back from STATA/SPSS preferences unless
fallback is disabled. Unfiltered downloads retain their original formats. Source
columns and values, including weights, are retained; estimates are not recalculated
and STATA/SPSS value labels are not added. Registered geographic/identifier columns
remain text when read, preserving leading zeros.

Results distinguish `ok`, `empty` (supported but no matching observations),
`partial` (unlocated source records or omitted data tables), `unavailable` (no verified
support), `failed` (source/schema/relationship failure), and `skipped` (cached output).
An empty partial subset does not establish that the area has no observations.
Unavailable selections never return national data; the reader raises
`GeographyUnavailable`. The report records selection, sources, geographic meaning,
source/selected/unlocated row counts, omissions, and the original status of cached
results. It is also available through `DataFrame.attrs["geography_report"]`.

The filter does not harmonize boundaries or infer residence from birth/work locations.
ENDES parent keys must be unique; filtering related tables never multiplies child
rows. District filtering does not establish district-level statistical representativeness.
Respect each survey's sampling design and estimation domains.

To extend coverage, review year-specific dictionaries and relationships, update the
explicit rules in `scripts/update_survey_geography.py`, then run it with
`--data-dir ./official-csv-zips`. It audits table schemas, encodings, and delimiters;
the variable index alone never enables a geographic adapter. Add meaningful tests
and verify against official data. Census behavior remains documented in the
[census guide](census.md#english).
