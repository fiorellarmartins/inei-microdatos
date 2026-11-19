"""Checks for optional runtime dependencies."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from typing import Optional


class OptionalDependencyError(ImportError):
    """Base error for missing or incompatible optional dependencies."""


class OptionalDependencyMissingError(OptionalDependencyError, ModuleNotFoundError):
    """An optional dependency is not installed."""


class ModuleUpgradeRequiredError(OptionalDependencyError):
    """An optional dependency is installed but its version is too old."""


def assert_optional_import(
    module_name: str,
    *,
    package_name: Optional[str] = None,
    extra: Optional[str] = None,
    min_version: Optional[str] = None,
    lib_name: str = "inei-microdatos",
) -> None:
    """Assert that an optional dependency is available before using it.

    The module is imported only to check that it exists; it is not returned,
    so import it normally afterwards.

    Parameters
    ----------
    module_name : str
        Importable name of the dependency (e.g. ``"pandas"``). Dotted names
        are allowed (e.g. ``"openpyxl.workbook"``).
    package_name : str, optional
        Distribution name on PyPI, when it differs from the module name.
        Defaults to the root of ``module_name``.
    extra : str, optional
        Name of the extra of this library that provides the dependency.
        If given, the install hint points to ``lib_name[extra]``.
    min_version : str, optional
        Minimum required version of the distribution, in PEP 440 format.
        The version is read from the installed package metadata, not from
        ``module.__version__``. If the metadata cannot be found, the check
        is skipped.
    lib_name : str, default "inei-microdatos"
        Name of this library, used in install and error messages.

    Raises
    ------
    OptionalDependencyMissingError
        If ``module_name`` cannot be imported. The message includes the
        ``pip`` and ``uv`` commands to install it.
    ModuleUpgradeRequiredError
        If the installed version is lower than ``min_version``.
    """
    root = module_name.split(".", 1)[0]
    dist = package_name or root

    try:
        import_module(module_name)
    except ModuleNotFoundError as exc:
        # Do not hide an ImportError raised from inside the dependency
        # (for example, pandas failing because numpy is missing).
        if exc.name and exc.name != root and not exc.name.startswith(root + "."):
            raise
        if extra:
            install_pip = f"pip install '{lib_name}[{extra}]'"
            install_uv = f"uv add '{lib_name}[{extra}]'"
        else:
            install_pip = f"pip install {dist}"
            install_uv = f"uv add {dist}"
        raise OptionalDependencyMissingError(
            f"'{module_name}' not found.\n"
            "Please install with either:\n"
            f"- {install_pip}\n"
            f"- {install_uv}",
            name=dist,
        ) from None

    if min_version is None:
        return

    try:
        found = distribution_version(dist)
    except PackageNotFoundError:
        return  # Cannot verify; do not block.

    from packaging.version import Version

    if Version(found) < Version(min_version):
        if extra:
            upgrade_pip = f"pip install --upgrade '{lib_name}[{extra}]'"
            upgrade_uv = f"uv add '{lib_name}[{extra}]'"
        else:
            upgrade_pip = f"pip install --upgrade {dist}"
            upgrade_uv = f"uv add {dist}"
        raise ModuleUpgradeRequiredError(
            f"{lib_name} requires {dist}>={min_version} (found {found}).\n"
            "Please upgrade with either:\n"
            f"- {upgrade_pip}\n"
            f"- {upgrade_uv}"
        )
