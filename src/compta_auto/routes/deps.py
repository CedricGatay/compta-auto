"""Shared FastAPI dependencies for route modules."""

from __future__ import annotations


# Sentinel functions used as dependency keys.
# The actual implementation is injected via app.dependency_overrides in app.py.


def get_repo():
    """Dependency placeholder — overridden in create_app()."""
    raise NotImplementedError("Must be overridden via dependency_overrides")


def get_settings():
    """Dependency placeholder — overridden in create_app()."""
    raise NotImplementedError("Must be overridden via dependency_overrides")


def get_db():
    """Dependency placeholder — overridden in create_app()."""
    raise NotImplementedError("Must be overridden via dependency_overrides")


def get_fernet():
    """Dependency placeholder — overridden in create_app()."""
    raise NotImplementedError("Must be overridden via dependency_overrides")
