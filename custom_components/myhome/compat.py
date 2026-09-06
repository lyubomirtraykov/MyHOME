"""Compatibility helpers across supported Home Assistant versions."""

from typing import Any

from homeassistant.helpers import device_registry as dr


_SUPPORTS_VIA_DEVICE_ID = "via_device_id" in getattr(
    dr.DeviceInfo, "__optional_keys__", ()
)


def first_scalar(value, default=None):
    """Return a scalar from legacy tuple/list config-entry values."""
    while isinstance(value, (list, tuple)):
        if not value:
            return default
        value = value[0]
    return default if value is None else value


def device_via_kwargs(
    gateway_device_id: str | None,
    gateway_identifier: tuple[str, str],
) -> dict[str, Any]:
    """Return the supported parent-device keyword for this HA version."""
    if _SUPPORTS_VIA_DEVICE_ID:
        return (
            {"via_device_id": gateway_device_id}
            if gateway_device_id is not None
            else {}
        )
    return {"via_device": gateway_identifier}
