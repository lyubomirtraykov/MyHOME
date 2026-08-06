"""Compatibility helpers for data created by older integration versions."""


def first_scalar(value, default=None):
    """Return a scalar from legacy tuple/list config-entry values."""
    while isinstance(value, (list, tuple)):
        if not value:
            return default
        value = value[0]
    return default if value is None else value
