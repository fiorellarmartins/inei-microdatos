[Volver al README](../README.md) · [English](#english)

# Censos de Población y Vivienda

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

---

<a name="english"></a>

[Back to README](../README.md#english)

# Population and Housing Censuses

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
