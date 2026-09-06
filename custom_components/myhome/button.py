"""Support for MyHome switches (light modules used for controlled outlets, relays)."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway import MyHOMEGatewayHandler

from homeassistant.components.button import (
    DOMAIN as PLATFORM,
    ButtonEntity,
)

from homeassistant.const import (
    CONF_NAME,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_WHO,
    CONF_WHERE,
    CONF_BUS_INTERFACE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
)
from .models import MyHomeConfigEntry
from .myhome_device import MyHOMEEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if PLATFORM not in config_entry.runtime_data.platforms_config:
        return

    _buttons: list[MyHOMEEntity] = []
    _configured_buttons = config_entry.runtime_data.platforms_config[PLATFORM]

    for _button in _configured_buttons:
        _disable_button = DisableCommandButtonEntity(
            hass=hass,
            platform=PLATFORM,
            device_id=_button,
            who=_configured_buttons[_button][CONF_WHO],
            where=_configured_buttons[_button][CONF_WHERE],
            interface=(
                _configured_buttons[_button].get(CONF_BUS_INTERFACE, None)
            ),
            name=_configured_buttons[_button][CONF_NAME],
            manufacturer=_configured_buttons[_button][CONF_MANUFACTURER],
            model=_configured_buttons[_button].get(CONF_DEVICE_MODEL),
            gateway=config_entry.runtime_data.gateway_handler,
        )
        _buttons.append(_disable_button)

        _enable_button = EnableCommandButtonEntity(
            hass=hass,
            platform=PLATFORM,
            device_id=_button,
            who=_configured_buttons[_button][CONF_WHO],
            where=_configured_buttons[_button][CONF_WHERE],
            interface=(
                _configured_buttons[_button].get(CONF_BUS_INTERFACE, None)
            ),
            name=_configured_buttons[_button][CONF_NAME],
            manufacturer=_configured_buttons[_button][CONF_MANUFACTURER],
            model=_configured_buttons[_button].get(CONF_DEVICE_MODEL),
            gateway=config_entry.runtime_data.gateway_handler,
        )
        _buttons.append(_enable_button)

    async_add_entities(_buttons)


class DisableCommandButtonEntity(ButtonEntity, MyHOMEEntity):
    def __init__(
        self,
        hass,
        platform: str,
        name: str,
        device_id: str,
        who: str,
        where: str,
        interface: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=platform,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )
        self._attr_name = "Lock"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:lock-alert"

        self._attr_entity_category = EntityCategory.CONFIG

        self._attr_unique_id = f"{gateway.mac}-{self._device_id}-disable"
        self._interface = interface
        self._full_where = (
            f"{self._where}#4#{self._interface}"
            if self._interface is not None
            else self._where
        )

        self._attr_extra_state_attributes = {
            "A": where[: len(where) // 2],
            "PL": where[len(where) // 2 :],
        }
        if self._interface is not None:
            self._attr_extra_state_attributes["Int"] = self._interface

    async def async_press(self) -> None:
        """Press the button."""
        await self._gateway_handler.send(f"*14*0*{self._full_where}##")


class EnableCommandButtonEntity(ButtonEntity, MyHOMEEntity):
    def __init__(
        self,
        hass,
        platform: str,
        name: str,
        device_id: str,
        who: str,
        where: str,
        interface: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=platform,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )
        self._attr_name = "Unlock"
        self._attr_has_entity_name = True
        self._attr_icon = "mdi:lock-open-variant-outline"

        self._attr_entity_category = EntityCategory.CONFIG

        self._attr_unique_id = f"{gateway.mac}-{self._device_id}-enable"
        self._interface = interface
        self._full_where = (
            f"{self._where}#4#{self._interface}"
            if self._interface is not None
            else self._where
        )

        self._attr_extra_state_attributes = {
            "A": where[: len(where) // 2],
            "PL": where[len(where) // 2 :],
        }
        if self._interface is not None:
            self._attr_extra_state_attributes["Int"] = self._interface

    async def async_press(self) -> None:
        """Press the button."""
        await self._gateway_handler.send(f"*14*1*{self._full_where}##")
