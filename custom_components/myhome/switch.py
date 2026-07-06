"""Support for MyHome switches (light modules used for controlled outlets, relays)."""
from homeassistant.components.switch import (
    DOMAIN as PLATFORM,
    SwitchDeviceClass,
    SwitchEntity,
)
from homeassistant.const import (
    CONF_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from OWNd.message import (
    OWNLightingEvent,
    OWNLightingCommand,
)

from .const import (
    CONF_ENTITY_NAME,
    CONF_ICON,
    CONF_ICON_ON,
    CONF_WHO,
    CONF_WHERE,
    CONF_BUS_INTERFACE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_CLASS,
    LOGGER,
)
from .models import MyHomeConfigEntry
from .myhome_device import MyHOMEEntity
from .gateway import MyHOMEGatewayHandler


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: MyHomeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if PLATFORM not in config_entry.runtime_data.platforms_config:
        return

    _switches: list[MyHOMESwitch] = []
    _configured_switches = config_entry.runtime_data.platforms_config[PLATFORM]

    for _switch in _configured_switches:
        _entity = MyHOMESwitch(
            hass=hass,
            device_id=_switch,
            who=_configured_switches[_switch][CONF_WHO],
            where=_configured_switches[_switch][CONF_WHERE],
            icon=_configured_switches[_switch][CONF_ICON],
            icon_on=_configured_switches[_switch][CONF_ICON_ON],
            interface=_configured_switches[_switch].get(CONF_BUS_INTERFACE, None),
            name=_configured_switches[_switch][CONF_NAME],
            entity_name=_configured_switches[_switch][CONF_ENTITY_NAME],
            device_class=_configured_switches[_switch][CONF_DEVICE_CLASS],
            manufacturer=_configured_switches[_switch][CONF_MANUFACTURER],
            model=_configured_switches[_switch][CONF_DEVICE_MODEL],
            gateway=config_entry.runtime_data.gateway_handler,
        )
        _switches.append(_entity)

    async_add_entities(_switches)


class MyHOMESwitch(MyHOMEEntity, SwitchEntity):
    def __init__(
        self,
        hass,
        name: str,
        entity_name: str,
        icon: str,
        icon_on: str,
        device_id: str,
        who: str,
        where: str,
        interface: str,
        device_class: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._attr_name = entity_name

        self._interface = interface
        self._full_where = f"{self._where}#4#{self._interface}" if self._interface is not None else self._where

        self._attr_extra_state_attributes = {
            "A": where[: len(where) // 2],
            "PL": where[len(where) // 2 :],
        }
        if self._interface is not None:
            self._attr_extra_state_attributes["Int"] = self._interface

        self._attr_device_class = SwitchDeviceClass.OUTLET if device_class.lower() == "outlet" else SwitchDeviceClass.SWITCH

        self._on_icon = icon_on
        self._off_icon = icon

        if self._off_icon is not None:
            self._attr_icon = self._off_icon

        self._attr_is_on = None

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        # _full_where includes the local bus interface (e.g. 12#4#01): the
        # status request must target the same object the commands do.
        await self._gateway_handler.send_status_request(OWNLightingCommand.status(self._full_where))

    async def async_turn_on(self, **kwargs):  # pylint: disable=unused-argument
        """Turn the device on."""
        await self._gateway_handler.send(OWNLightingCommand.switch_on(self._full_where))

    async def async_turn_off(self, **kwargs):  # pylint: disable=unused-argument
        """Turn the device off."""
        await self._gateway_handler.send(OWNLightingCommand.switch_off(self._full_where))

    def handle_event(self, message: OWNLightingEvent):
        """Handle an event message."""
        if self._attr_device_class == SwitchDeviceClass.SWITCH:
            LOGGER.info(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log.replace("Light", "Switch"),
            )
        elif self._attr_device_class == SwitchDeviceClass.OUTLET:
            LOGGER.info(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log.replace("Light", "Outlet"),
            )
        else:
            LOGGER.info(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
        # is_on is None for frames that carry no on/off state: keep the
        # last known state instead of overwriting it.
        if message.is_on is not None:
            self._attr_is_on = message.is_on
        if self._off_icon is not None and self._on_icon is not None:
            self._attr_icon = self._on_icon if self._attr_is_on else self._off_icon
        self.async_schedule_update_ha_state()
