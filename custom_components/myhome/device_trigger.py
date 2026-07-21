"""Device triggers for MyHOME CEN / CEN+ scenario controls.

Wall controls carry no state, so they own no entity: they are registered as
devices the first time a button is pressed (see
``MyHOMEGatewayHandler._register_scenario_control``) purely so their buttons can
be picked from the automation UI instead of hand-written YAML event triggers.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_EVENT_DATA,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    CEN_KIND,
    CEN_PLUS_KIND,
    CONF_LONG_PRESS,
    CONF_LONG_RELEASE,
    CONF_SHORT_PRESS,
    CONF_SHORT_RELEASE,
    DOMAIN,
    SCENARIO_CONTROL_BUTTONS,
    SCENARIO_CONTROL_EVENTS,
)

# Not a shared HA constant: device-trigger platforms define it themselves.
CONF_SUBTYPE = "subtype"

# Press states each kind of control can report. CEN+ has no distinct
# "released after a short press": a short press is a single event.
TRIGGER_TYPES: dict[str, tuple[str, ...]] = {
    CEN_KIND: (
        CONF_SHORT_PRESS,
        CONF_SHORT_RELEASE,
        CONF_LONG_PRESS,
        CONF_LONG_RELEASE,
    ),
    CEN_PLUS_KIND: (
        CONF_SHORT_PRESS,
        CONF_LONG_PRESS,
        CONF_LONG_RELEASE,
    ),
}

# One subtype per button, so the UI shows two dropdowns (what happened / which
# button) instead of one long flat list.
SUBTYPE_PREFIX = "button_"
SUBTYPES = [f"{SUBTYPE_PREFIX}{button}" for button in SCENARIO_CONTROL_BUTTONS]

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(
            {t for types in TRIGGER_TYPES.values() for t in types}
        ),
        vol.Required(CONF_SUBTYPE): vol.In(SUBTYPES),
    }
)


def _control_from_device(
    hass: HomeAssistant, device_id: str
) -> tuple[str, str, int] | None:
    """Return (mac, kind, object_id) if the device is a CEN/CEN+ control."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return None
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        for kind in (CEN_PLUS_KIND, CEN_KIND):
            # Identifier layout: "<mac>-<kind>-<object_id>" (see const.py).
            marker = f"-{kind}-"
            if marker in identifier:
                mac, _, object_id = identifier.partition(marker)
                if object_id.isdigit():
                    return mac, kind, int(object_id)
    return None


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List the triggers a CEN/CEN+ control offers."""
    control = _control_from_device(hass, device_id)
    if control is None:
        return []
    _mac, kind, _object_id = control

    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
            CONF_SUBTYPE: subtype,
        }
        for trigger_type in TRIGGER_TYPES[kind]
        for subtype in SUBTYPES
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE | None:
    """Attach a trigger to the underlying bus event."""
    control = _control_from_device(hass, config[CONF_DEVICE_ID])
    if control is None:
        return None
    mac, kind, object_id = control

    pushbutton = int(config[CONF_SUBTYPE].removeprefix(SUBTYPE_PREFIX))

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: SCENARIO_CONTROL_EVENTS[kind],
            CONF_EVENT_DATA: {
                # mac disambiguates controls with the same object id on
                # different gateways.
                "mac": mac,
                "object": object_id,
                "pushbutton": pushbutton,
                "event": config[CONF_TYPE],
            },
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
