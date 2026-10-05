"""CLI for inei-microdatos."""

from __future__ import annotations

from pathlib import Path

import click
import requests

from inei_microdatos.catalog import (
    build_catalog,
    catalog_age,
    catalog_stats,
    filter_catalog,
    load_catalog,
    save_catalog,
)
from inei_microdatos.client import INEIClient
from inei_microdatos.download import LAYOUTS, download_docs, download_modules

DEFAULT_CATALOG = Path.home() / ".inei-microdatos" / "catalog.json"

SURVEY_HELP = 'Survey name or alias (e.g. "enaho", "endes", "censo"). Run `aliases` to see all.'
CATALOG_HELP = "Path to catalog JSON file (defaults to bundled catalog)."
LAYOUT_HELP = (
    "Folder layout for downloaded files. Presets: "
    + ", ".join(f'"{k}" ({v})' for k, v in LAYOUTS.items())
    + '. Or a custom template with {survey}, {year}, {period}, {code}, {module_name}, {format}.'
)


@click.group()
@click.version_option()
def cli():
    """INEI Microdatos — programmatic access to Peru's national statistics microdata.

    \b
    Quick start:
      inei-microdatos list --survey enaho
      inei-microdatos download --survey endes --year-min 2024 --format CSV --dest ./data/
      inei-microdatos read ./data/968-Modulo1629.zip --info
      inei-microdatos aliases
    """


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG),
              help=CATALOG_HELP)
@click.option("--refresh", is_flag=True, help="Force re-crawl even if catalog exists.")
@click.option("--survey", multiple=True, help=SURVEY_HELP)
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
def crawl(catalog_path, refresh, survey, year_min, year_max):
    """Crawl the INEI portal and build/update the local catalog."""
    catalog_path = Path(catalog_path)

    if catalog_path.exists() and not refresh:
        click.echo(f"Catalog already exists at {catalog_path}")
        click.echo("Use --refresh to re-crawl.")
        return

    client = INEIClient()
    yr = (year_min or 1990, year_max or 2030) if year_min or year_max else None
    catalog = build_catalog(
        client=client,
        surveys=list(survey) if survey else None,
        years=yr,
    )
    save_catalog(catalog, catalog_path)
    stats = catalog_stats(catalog)
    click.echo(f"\nSaved to {catalog_path}")
    _print_stats(stats)


@cli.command("list")
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG),
              help=CATALOG_HELP)
@click.option("--survey", help=SURVEY_HELP)
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
@click.option("--period", help="Filter to periods matching this substring.")
def list_cmd(catalog_path, survey, year_min, year_max, period):
    """List surveys and their available data.

    \b
    Examples:
      inei-microdatos list
      inei-microdatos list --survey enaho --year-min 2020
      inei-microdatos list --survey cenagro
    """
    catalog = load_catalog(catalog_path)
    catalog = filter_catalog(catalog, survey=survey, year_min=year_min, year_max=year_max, period=period)

    if not catalog:
        click.echo("No matching surveys found.")
        return

    for entry in catalog:
        years = sorted(entry["years"].keys())
        n_mods = sum(
            len(p["modules"])
            for yd in entry["years"].values()
            for p in yd.values()
        )
        n_docs = sum(
            len(p["docs"])
            for yd in entry["years"].values()
            for p in yd.values()
        )
        yr_range = f"{years[0]}-{years[-1]}" if years else "N/A"
        click.echo(f"  [{entry['category'][:3]}] {entry['label']}")
        if entry.get("data_kind") == "aggregate_tables":
            click.echo("        Aggregated tables | National selection (Perú), not microdata")
            for year in years:
                for period_data in entry["years"][year].values():
                    formats = sorted({f for m in period_data["modules"] for f in ("XLS", "XLSX") if m.get(f.lower() + "_url") or (f == "XLS" and m.get("redatam_query"))})
                    if formats:
                        click.echo(f"        {year}: {len(period_data['modules'])} modules | {', '.join(formats)}")
                        if period_data.get("access") == "query_export":
                            click.echo("          REDATAM national frequencies generated on demand")
                    else:
                        click.echo(f"        {year}: online query only; no automated downloads")
                        for resource in period_data.get("resources", []):
                            click.echo(f"          {resource['name']}: {resource['url']}")
        click.echo(f"        {yr_range} | {len(years)} years | {n_mods} modules | {n_docs} docs")


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG),
              help=CATALOG_HELP)
@click.option("--survey", help=SURVEY_HELP)
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
@click.option("--period", help="Filter to periods matching this substring.")
@click.option("--format", "fmt", type=click.Choice(["CSV", "STATA", "SPSS", "XLSX", "XLS"], case_sensitive=False), default="CSV",
              help="Download format (default: CSV).")
@click.option("--dest", type=click.Path(), required=True, help="Destination directory.")
@click.option("--layout", default="default", help=LAYOUT_HELP)
@click.option("--workers", type=int, default=4, help="Parallel download threads (default: 4).")
@click.option("--no-fallback", is_flag=True, help="Don't fall back to another format when preferred isn't available.")
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded without downloading.")
@click.option("--include-docs", is_flag=True, help="Also download documentation.")
@click.option("--ubigeo", help="Census INEI code: 2 digits department, 4 province, 6 district.")
def download(catalog_path, survey, year_min, year_max, period, fmt, dest, layout, workers, no_fallback, dry_run, include_docs, ubigeo):
    """Download microdata files or aggregate census tables.

    \b
    Examples:
      inei-microdatos download --survey endes --year-min 2024 --format CSV --dest ./data/
      inei-microdatos download --survey enaho --period Anual --format STATA --dest ./data/
      inei-microdatos download --survey endes --dest ./data/ --dry-run
    """
    catalog = load_catalog(catalog_path)
    catalog = filter_catalog(catalog, survey=survey, year_min=year_min, year_max=year_max, period=period)

    if not catalog:
        click.echo("No matching data found.")
        return

    stats = catalog_stats(catalog)
    click.echo(f"Matched: {stats['surveys']} surveys, {stats['downloadable_modules']} downloadable modules")

    if any(e.get("data_kind") == "aggregate_tables" for e in catalog):
        if ubigeo:
            click.echo(f"Census geographic selection: {ubigeo}. XLSX files contain derived subsets; tables without this geography are reported as unavailable.")
        else:
            click.echo("Population and housing census: original aggregate XLS/XLSX tables; no microdata or CSV conversion.")
        for entry in catalog:
            for year, periods in entry["years"].items():
                for data in periods.values():
                    if data.get("access") == "query_export":
                        scope = f"ubigeo {ubigeo}" if ubigeo else "national"
                        click.echo(f"{year}: generating {scope} REDATAM frequency tables; server requests run sequentially.")
                    if data.get("access") == "online_query":
                        click.echo(f"{year}: online query only; automated download unavailable.")
                        for resource in data.get("resources", []):
                            click.echo(f"  {resource['url']}")

    try:
        result = download_modules(catalog, dest, fmt=fmt, fallback=not no_fallback, layout=layout, workers=workers, dry_run=dry_run, ubigeo=ubigeo)
    except (ValueError, requests.RequestException) as exc:
        raise click.ClickException(str(exc)) from exc
    if dry_run:
        if include_docs:
            click.echo("\nDocumentation:")
            download_docs(catalog, dest, layout=layout, dry_run=True)
        return

    click.echo(f"\nModules: {result['ok']} downloaded, {result['skipped']} skipped, {result['failed']} failed, {result['bad_zip']} bad")
    if result.get("unavailable"):
        click.echo(f"{result['unavailable']} modules have no tables for ubigeo {ubigeo}.")

    if include_docs:
        doc_result = download_docs(catalog, dest, layout=layout, workers=workers)
        click.echo(f"Docs: {doc_result['ok']} downloaded, {doc_result['skipped']} skipped, {doc_result['failed']} failed")


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG),
              help=CATALOG_HELP)
@click.option("--survey", help=SURVEY_HELP)
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
@click.option("--dest", type=click.Path(), required=True, help="Destination directory.")
@click.option("--layout", default="default", help=LAYOUT_HELP)
@click.option("--workers", type=int, default=4, help="Parallel download threads (default: 4).")
def docs(catalog_path, survey, year_min, year_max, dest, layout, workers):
    """Download documentation files only (questionnaires, dictionaries, fichas).

    \b
    Examples:
      inei-microdatos docs --survey endes --year-min 2020 --dest ./docs/
      inei-microdatos docs --survey enaho --year-min 2024 --dest ./docs/
    """
    catalog = load_catalog(catalog_path)
    catalog = filter_catalog(catalog, survey=survey, year_min=year_min, year_max=year_max)

    if not catalog:
        click.echo("No matching data found.")
        return

    result = download_docs(catalog, dest, layout=layout, workers=workers)
    click.echo(f"\nDocs: {result['ok']} downloaded, {result['skipped']} skipped, {result['failed']} failed")


@cli.command()
@click.argument("source")
@click.option("--table", "-t", multiple=True, help="Table names to read (reads all if omitted).")
@click.option("--format", "fmt", type=click.Choice(["csv", "stata", "spss", "xlsx", "xls"], case_sensitive=False),
              help="Format hint (auto-detected if omitted).")
@click.option("--info", is_flag=True, help="Just list tables or workbook sheets, don't read.")
def read(source, table, fmt, info):
    """Read a module ZIP, XLSX workbook, or census XLS export and show its contents.

    \b
    SOURCE can be a path to a ZIP file or a download code like "968-Modulo1629".

    \b
    Examples:
      inei-microdatos read ./data/968-Modulo1629.zip --info
      inei-microdatos read ./data/968-Modulo1629.zip -t RECH0
      inei-microdatos read 968-Modulo1629
    """
    from inei_microdatos.reader import list_tables, read_module

    if info:
        tables = list_tables(source)
        if not tables:
            click.echo("No data tables found.")
            return
        click.echo(f"{'Table':<30} {'Format':<8} {'Size':>12}")
        click.echo("-" * 52)
        for t in tables:
            size_mb = t["size_bytes"] / 1024 / 1024
            click.echo(f"{t['name']:<30} {t['format']:<8} {size_mb:>9.1f} MB")
        return

    dfs = read_module(source, tables=list(table) if table else None, fmt=fmt)

    if not dfs:
        click.echo("No data files found.")
        return

    for name, df in dfs.items():
        click.echo(f"\n=== {name} ({len(df)} rows, {len(df.columns)} columns) ===")
        click.echo(f"Columns: {', '.join(map(str, df.columns[:15]))}")
        if len(df.columns) > 15:
            click.echo(f"  ... +{len(df.columns) - 15} more")
        click.echo(df.head(5).to_string())


@cli.command("search")
@click.argument("query")
@click.option("--survey", help=SURVEY_HELP)
@click.option("--year", help="Filter to this year.")
@click.option("--module", help="Filter to module name substring.")
@click.option("--exact", is_flag=True, help="Match variable name exactly.")
def search_cmd(query, survey, year, module, exact):
    """Search variables and census tables by name or label.

    \b
    Examples:
      inei-microdatos search ingreso
      inei-microdatos search p21 --survey enaho --exact
      inei-microdatos search "material predominante" --year 2024
    """
    from inei_microdatos.variables import search

    try:
        results = search(query, survey=survey, year=year, module=module, exact=exact)
    except FileNotFoundError as e:
        click.echo(str(e))
        return

    if not results:
        click.echo(f'No variables or tables matching "{query}" found.')
        return

    click.echo(f'{len(results)} matches for "{query}":\n')

    # Group by variable name
    by_var = {}
    for r in results:
        if r["kind"] == "table":
            click.echo(f"  [table] {r['variable']} | {r['year']}")
            click.echo(f"    {r['label']}")
            click.echo(f"    {r['module_code']} | {r['module_name']}\n")
            continue
        key = r["variable"]
        if key not in by_var:
            by_var[key] = []
        by_var[key].append(r)

    for var_name, matches in sorted(by_var.items()):
        years = sorted(set(m["year"] for m in matches))
        label = matches[0]["label"] or ""
        surveys = sorted(set(m["survey"][:40] for m in matches))
        yr_str = f"{years[0]}-{years[-1]}" if len(years) > 1 else years[0]
        click.echo(f"  {var_name:<20} {label[:50]}")
        if any(m["data_kind"] == "aggregate_tables" for m in matches):
            click.echo("                       [REDATAM variable; aggregate query output]")
        click.echo(f"  {'':20} {surveys[0]} | {yr_str} ({len(years)} years, {len(matches)} modules)")
        if len(surveys) > 1:
            for s in surveys[1:]:
                click.echo(f"  {'':20} {s}")
        click.echo()


@cli.command("track")
@click.argument("variable")
@click.option("--survey", help=SURVEY_HELP)
def track_cmd(variable, survey):
    """Track a variable across years — shows when it appears, changes, or disappears.

    \b
    Examples:
      inei-microdatos track p21 --survey enaho
      inei-microdatos track p101
    """
    from inei_microdatos.variables import search_across_years

    try:
        by_year = search_across_years(variable, survey=survey)
    except FileNotFoundError as e:
        click.echo(str(e))
        return

    if not by_year:
        click.echo(f'Variable "{variable}" not found in any indexed module.')
        return

    click.echo(f'Variable "{variable}" across years:\n')

    prev_label = None
    for yr, matches in by_year.items():
        labels = set(m["label"] for m in matches if m["label"])
        modules = [m["module_code"] for m in matches]
        label = next(iter(labels)) if labels else ""

        changed = ""
        if prev_label is not None and label != prev_label:
            changed = "  ** label changed"
        prev_label = label

        click.echo(f"  {yr}  {label[:55]}{changed}")
        if len(modules) > 1:
            click.echo(f"  {'':6}{len(modules)} modules: {', '.join(modules[:5])}")

    # Summary
    all_years = sorted(by_year.keys())
    click.echo(f"\n  Present in {len(all_years)} years ({all_years[0]}-{all_years[-1]})")


@cli.command("index")
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG),
              help=CATALOG_HELP)
@click.option("--survey", help=SURVEY_HELP + " Required.", required=True)
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
@click.option("--period", help="Filter to periods matching this substring.")
@click.option("--dest", type=click.Path(), default=str(Path.home() / ".inei-microdatos" / "variable_index.json.gz"),
              help="Where to save the index.")
@click.option("--workers", type=int, default=4, help="Parallel download threads (default: 4).")
@click.option("--data-dir", type=click.Path(exists=True, file_okay=False),
              help="Reuse downloaded census XLSX files under this directory.")
def index_cmd(catalog_path, survey, year_min, year_max, period, dest, workers, data_dir):
    """Index survey variables or census source variables and table titles.

    \b
    Reads ZIP metadata or census workbook titles and removes temporary files.
    REDATAM variable names and 2007 table titles use catalog metadata directly.

    \b
    Examples:
      inei-microdatos index --survey enaho
      inei-microdatos index --survey enaho --year-min 2020
      inei-microdatos index --survey endes --year-min 2024
      inei-microdatos index --survey censo --data-dir ./data
    """
    from inei_microdatos.variables import build_index

    catalog = load_catalog(catalog_path)
    catalog = filter_catalog(catalog, survey=survey, year_min=year_min, year_max=year_max, period=period)

    if not catalog:
        click.echo("No matching data found.")
        return

    n_mods = sum(len(p["modules"]) for e in catalog for y in e["years"].values() for p in y.values())
    click.echo(f"Indexing {n_mods} modules...")

    new_entries = build_index(catalog, dest=dest, workers=workers, data_dir=data_dir)

    click.echo(f"\nIndexed {len(new_entries)} modules.")
    total_vars = sum(v.get("kind", "variable") == "variable" for e in new_entries for v in e["variables"])
    total_tables = sum(v.get("kind") == "table" for e in new_entries for v in e["variables"])
    click.echo(f"Total variables: {total_vars}")
    if total_tables:
        click.echo(f"Total census tables: {total_tables}")
    click.echo(f"Saved to {dest}")


@cli.command()
def aliases():
    """List available short survey aliases.

    \b
    Aliases work everywhere --survey is accepted: list, download, docs, crawl.

    \b
    Examples:
      inei-microdatos aliases
      inei-microdatos list --survey enaho
      inei-microdatos download --survey endes --dest ./data/
    """
    from inei_microdatos.aliases import ALIASES
    click.echo(f"{'Alias':<20} {'Matches'}")
    click.echo("-" * 70)
    for alias, target in sorted(ALIASES.items()):
        click.echo(f"{alias:<20} {target}")


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG),
              help=CATALOG_HELP)
def stats(catalog_path):
    """Show catalog statistics.

    \b
    Examples:
      inei-microdatos stats
    """
    catalog = load_catalog(catalog_path)
    age = catalog_age(catalog_path)
    _print_stats(catalog_stats(catalog))
    if age:
        click.echo(f"  Catalog crawled at:   {age}")
    else:
        click.echo("  Catalog crawled at:   unknown (legacy format)")


def _print_stats(s: dict):
    click.echo(f"  Surveys:              {s['surveys']}")
    click.echo(f"  Survey-years:         {s['survey_years']}")
    click.echo(f"  Modules:              {s['modules']}")
    click.echo(f"  Downloadable modules: {s['downloadable_modules']}")
    click.echo(f"  Documentation files:  {s['docs']}")
