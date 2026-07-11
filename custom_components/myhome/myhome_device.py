"""Support for common values for MyHome devices."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway import MyHOMEGatewayHandler

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from OWNd.message import OWNMessage

from .const import DOMAIN


class MyHOMEEntity(Entity):
    def __init__(
        self,
        hass,
        name: str,
        platform: str,
        device_id: str,
        who: str,
        where: str,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        self._hass = hass
        self._platform = platform
        self._who = who
        self._where = where
        self._device_id = device_id
        self._attr_unique_id = f"{gateway.mac}-{self._device_id}"
        self._manufacturer = manufacturer or "BTicino S.p.A."
        self._model = model
        self._gateway_handler = gateway
        self._attr_has_entity_name = True
        self._attr_name = None
        self._attr_entity_registry_enabled_default = True
        self._attr_should_poll = False

        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{gateway.mac}-{self._device_id}")},
            "name": name,
            "manufacturer": self._manufacturer,
            "model": self._model,
            "via_device": (DOMAIN, self._gateway_handler.unique_id),
        }

    @property
    def available(self) -> bool:
        """Entities are available only while the gateway is (grace-filtered)."""
        return self._gateway_handler.available

    @callback
    def _handle_availability_update(self) -> None:
        """Re-render availability when the gateway connection state changes."""
        self.async_write_ha_state()

    @callback
    def _handle_message(self, message: OWNMessage) -> None:
        """Deliver a bus message addressed to this device to the handler."""
        self.handle_event(message)

    def handle_event(self, message: OWNMessage) -> None:
        """Handle a bus message addressed to this device.

        Default: ignore. Stateful entities override this; write-only ones
        (e.g. the lock/unlock buttons) simply inherit the no-op.
        """

    async def async_update(self) -> None:
        """Request a state refresh from the gateway.

        Default: nothing to poll. Entities with a queryable state override
        this with the appropriate status request.
        """

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        # Keep the cooperative MRO chain intact: entities that also inherit
        # RestoreEntity (motion sensor, HA's ButtonEntity) rely on their
        # async_added_to_hass running too, or their state is never saved for
        # the next restart.
        await super().async_added_to_hass()
        # Receive every bus message addressed to this device. Replaces the
        # old self-registration into a shared hass.data dict: subscription is
        # cleaned up automatically on removal, and a message for a device
        # without subscribers dies silently instead of risking a KeyError.
        self.async_on_remove(
            async_dispatcher_connect(
                self._hass,
                self._gateway_handler.entity_signal(self._device_id),
                self._handle_message,
            )
        )
        # Re-render this entity whenever the gateway availability flips.
        self.async_on_remove(
            async_dispatcher_connect(
                self._hass,
                self._gateway_handler.availability_signal,
                self._handle_availability_update,
            )
        )
        await self.async_update()
