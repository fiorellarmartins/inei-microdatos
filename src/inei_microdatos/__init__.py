"""Programmatic access to INEI Peru's microdata portal."""

from inei_microdatos.client import INEIClient
from inei_microdatos.catalog import build_catalog, load_catalog, save_catalog, catalog_age
from inei_microdatos.download import download_modules, download_docs, LAYOUTS
from inei_microdatos.reader import read_module, read_catalog_entry, list_tables
from inei_microdatos.variables import search as search_variables, search_across_years

__version__ = "0.2.0"
__all__ = [
    "INEIClient",
    "build_catalog",
    "load_catalog",
    "save_catalog",
    "download_modules",
    "download_docs",
    "read_module",
    "read_catalog_entry",
    "list_tables",
    "LAYOUTS",
]
