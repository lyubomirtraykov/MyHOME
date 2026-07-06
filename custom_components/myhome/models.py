"""Typed runtime data for the MyHOME integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .gateway import MyHOMEGatewayHandler


@dataclass
class MyHomeRuntimeData:
    """Everything a loaded MyHOME config entry needs at runtime.

    Replaces the old shared ``hass.data[DOMAIN][mac]...`` nested dict: typed,
    per-entry, and impossible to index with a missing key by construction.
    """

    gateway_handler: MyHOMEGatewayHandler
    # platform -> device_id ("who-where") -> validated device configuration
    platforms_config: dict[str, dict[str, Any]]


type MyHomeConfigEntry = ConfigEntry[MyHomeRuntimeData]
