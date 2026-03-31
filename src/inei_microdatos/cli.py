"""CLI for inei-microdatos."""

from __future__ import annotations

from pathlib import Path

import click

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

LAYOUT_HELP = (
    "Folder layout for downloaded files. Presets: "
    + ", ".join(f'"{k}" ({v})' for k, v in LAYOUTS.items())
    + '. Or a custom template with {survey}, {year}, {period}, {code}, {module_name}, {format}.'
)


@click.group()
@click.version_option()
def cli():
    """INEI Microdatos — programmatic access to Peru's national statistics microdata."""


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG),
              help="Path to catalog JSON file.")
@click.option("--refresh", is_flag=True, help="Force re-crawl even if catalog exists.")
@click.option("--survey", multiple=True, help="Filter to surveys matching this substring.")
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
              help="Path to catalog JSON file.")
@click.option("--survey", help="Filter to surveys matching this substring.")
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
@click.option("--period", help="Filter to periods matching this substring.")
def list_cmd(catalog_path, survey, year_min, year_max, period):
    """List surveys and their available data."""
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
        click.echo(f"        {yr_range} | {len(years)} years | {n_mods} modules | {n_docs} docs")


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG))
@click.option("--survey", help="Filter to surveys matching this substring.")
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
@click.option("--period", help="Filter to periods matching this substring.")
@click.option("--format", "fmt", type=click.Choice(["CSV", "STATA", "SPSS"], case_sensitive=False), default="CSV")
@click.option("--dest", type=click.Path(), required=True, help="Destination directory.")
@click.option("--layout", default="default", help=LAYOUT_HELP)
@click.option("--workers", type=int, default=4, help="Parallel download threads.")
@click.option("--no-fallback", is_flag=True, help="Don't fall back to another format when preferred isn't available.")
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded without downloading.")
@click.option("--include-docs", is_flag=True, help="Also download documentation.")
def download(catalog_path, survey, year_min, year_max, period, fmt, dest, layout, workers, no_fallback, dry_run, include_docs):
    """Download microdata files.

    SURVEY can be a short alias (e.g. "enaho", "endes") or a substring of the full name.
    """
    catalog = load_catalog(catalog_path)
    catalog = filter_catalog(catalog, survey=survey, year_min=year_min, year_max=year_max, period=period)

    if not catalog:
        click.echo("No matching data found.")
        return

    stats = catalog_stats(catalog)
    click.echo(f"Matched: {stats['surveys']} surveys, {stats['downloadable_modules']} downloadable modules")

    result = download_modules(catalog, dest, fmt=fmt, fallback=not no_fallback, layout=layout, workers=workers, dry_run=dry_run)
    if dry_run:
        if include_docs:
            click.echo("\nDocumentation:")
            download_docs(catalog, dest, layout=layout, dry_run=True)
        return

    click.echo(f"\nModules: {result['ok']} downloaded, {result['skipped']} skipped, {result['failed']} failed, {result['bad_zip']} bad")

    if include_docs:
        doc_result = download_docs(catalog, dest, layout=layout, workers=workers)
        click.echo(f"Docs: {doc_result['ok']} downloaded, {doc_result['skipped']} skipped, {doc_result['failed']} failed")


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG))
@click.option("--survey", help="Filter to surveys matching this substring.")
@click.option("--year-min", type=int, help="Minimum year.")
@click.option("--year-max", type=int, help="Maximum year.")
@click.option("--dest", type=click.Path(), required=True, help="Destination directory.")
@click.option("--layout", default="default", help=LAYOUT_HELP)
@click.option("--workers", type=int, default=4)
def docs(catalog_path, survey, year_min, year_max, dest, layout, workers):
    """Download documentation files only."""
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
@click.option("--format", "fmt", type=click.Choice(["csv", "stata", "spss"], case_sensitive=False),
              help="Format hint (auto-detected if omitted).")
@click.option("--info", is_flag=True, help="Just list tables inside the ZIP, don't read.")
def read(source, table, fmt, info):
    """Read a module ZIP and show its contents.

    SOURCE can be a path to a ZIP file or a download code like "968-Modulo1629".
    """
    from inei_microdatos.reader import list_tables, read_module

    if info:
        tables = list_tables(source)
        if not tables:
            click.echo("No data files found in ZIP.")
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
        click.echo(f"Columns: {', '.join(df.columns[:15])}")
        if len(df.columns) > 15:
            click.echo(f"  ... +{len(df.columns) - 15} more")
        click.echo(df.head(5).to_string())


@cli.command()
def aliases():
    """List available short survey aliases."""
    from inei_microdatos.aliases import ALIASES
    click.echo(f"{'Alias':<20} {'Matches'}")
    click.echo("-" * 70)
    for alias, target in sorted(ALIASES.items()):
        click.echo(f"{alias:<20} {target}")


@cli.command()
@click.option("--catalog", "catalog_path", type=click.Path(), default=str(DEFAULT_CATALOG))
def stats(catalog_path):
    """Show catalog statistics."""
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
