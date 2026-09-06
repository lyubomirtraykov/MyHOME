"""MyHOME integration."""

from __future__ import annotations

import yaml
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR
from homeassistant.components.button import DOMAIN as BUTTON
from homeassistant.components.sensor import DOMAIN as SENSOR
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_FRIENDLY_NAME, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType
from OWNd.message import OWNCommand, OWNGatewayCommand
from voluptuous import Invalid

from .const import (
    ATTR_GATEWAY,
    ATTR_MESSAGE,
    CEN_KIND,
    CEN_PLUS_KIND,
    CONF_DEVICE_TYPE,
    CONF_DEVICE_CLASS,
    CONF_ENTITIES,
    CONF_FILE_PATH,
    CONF_FIRMWARE,
    CONF_GENERATE_EVENTS,
    CONF_MANUFACTURER,
    CONF_MANUFACTURER_URL,
    CONF_PLATFORMS,
    CONF_SSDP_LOCATION,
    CONF_SSDP_ST,
    CONF_UDN,
    CONF_WORKER_COUNT,
    DOMAIN,
    LOGGER,
)
from .compat import first_scalar
from .gateway import MyHOMEGatewayHandler
from .models import MyHomeConfigEntry, MyHomeRuntimeData
from .validate import config_schema, format_mac

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LEGACY_DISCOVERY_FIELDS = (
    CONF_SSDP_LOCATION,
    CONF_SSDP_ST,
    CONF_DEVICE_TYPE,
    CONF_FRIENDLY_NAME,
    CONF_MANUFACTURER,
    CONF_MANUFACTURER_URL,
    CONF_NAME,
    CONF_FIRMWARE,
    CONF_UDN,
)


async def async_migrate_entry(
    hass: HomeAssistant, entry: MyHomeConfigEntry
) -> bool:
    """Migrate config entries created before scalar discovery values were fixed."""
    if entry.version >= 2:
        return True

    data = dict(entry.data)
    for field in _LEGACY_DISCOVERY_FIELDS:
        if field in data:
            default = "BTicino S.p.A." if field == CONF_MANUFACTURER else None
            data[field] = first_scalar(data[field], default)

    hass.config_entries.async_update_entry(entry, data=data, version=2)
    LOGGER.info("Migrated MyHOME config entry %s to version 2", entry.entry_id)
    return True


def _is_scenario_control(device_entry: dr.DeviceEntry) -> bool:
    """True for the stateless CEN/CEN+ controls registered on first press."""
    return any(
        domain == DOMAIN
        and (f"-{CEN_KIND}-" in identifier or f"-{CEN_PLUS_KIND}-" in identifier)
        for domain, identifier in device_entry.identifiers
    )


def _resolve_gateway_handler(
    hass: HomeAssistant, gateway_mac: str | None
) -> MyHOMEGatewayHandler | None:
    """Return the handler for the requested gateway.

    With no MAC given, the first loaded gateway is used (the common
    single-gateway setup). Only LOADED entries have runtime_data.
    """
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if gateway_mac is None:
        return loaded[0].runtime_data.gateway_handler if loaded else None
    for entry in loaded:
        if entry.data[CONF_MAC] == gateway_mac:
            return entry.runtime_data.gateway_handler
    return None


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the MyHOME component."""

    # The services are global, not tied to a single config entry: register
    # them once here, so loading/unloading one gateway can never remove them
    # for another. The target gateway is resolved at call time.

    async def handle_sync_time(call: ServiceCall) -> None:
        gateway = call.data.get(ATTR_GATEWAY, None)
        if gateway is not None:
            gateway = format_mac(gateway)
            if gateway is None:
                LOGGER.error(
                    "Invalid gateway mac `%s`, could not send time synchronisation message.",
                    call.data.get(ATTR_GATEWAY),
                )
                return
        handler = _resolve_gateway_handler(hass, gateway)
        if handler is None:
            LOGGER.error(
                "Gateway `%s` not found or not loaded, could not send time synchronisation message.",
                gateway,
            )
            return
        await handler.send(
            OWNGatewayCommand.set_datetime_to_now(hass.config.time_zone)
        )

    hass.services.async_register(DOMAIN, "sync_time", handle_sync_time)

    async def handle_send_message(call: ServiceCall) -> None:
        gateway = call.data.get(ATTR_GATEWAY, None)
        message = call.data.get(ATTR_MESSAGE, None)
        if gateway is not None:
            gateway = format_mac(gateway)
            if gateway is None:
                LOGGER.error(
                    "Invalid gateway mac `%s`, could not send message `%s`.",
                    call.data.get(ATTR_GATEWAY),
                    message,
                )
                return
        LOGGER.debug("Handling message `%s` to be sent to `%s`", message, gateway)
        handler = _resolve_gateway_handler(hass, gateway)
        if handler is None:
            LOGGER.error(
                "Gateway `%s` not found or not loaded, could not send message `%s`.",
                gateway,
                message,
            )
            return
        if message is None:
            return
        own_message = OWNCommand.parse(message)
        if own_message is None:
            LOGGER.error("Could not parse message `%s`, not sending it.", message)
            return
        if own_message.is_valid:
            LOGGER.debug(
                "%s Sending valid OpenWebNet Message: `%s`",
                handler.log_id,
                own_message,
            )
            await handler.send(own_message)

    hass.services.async_register(DOMAIN, "send_message", handle_send_message)

    if DOMAIN not in config:
        return True

    LOGGER.error("configuration.yaml not supported for this component!")

    return False


async def async_setup_entry(hass: HomeAssistant, entry: MyHomeConfigEntry) -> bool:
    _config_file_path = (
        str(entry.options[CONF_FILE_PATH])
        if CONF_FILE_PATH in entry.options
        else "/config/myhome.yaml"
    )
    _generate_events = entry.options.get(CONF_GENERATE_EVENTS, False)

    def _load_config_file():
        # File I/O and YAML parsing are blocking: keep them off the event loop.
        with open(_config_file_path, encoding="utf-8") as yaml_file:
            return yaml.safe_load(yaml_file)

    try:
        _raw_config = await hass.async_add_executor_job(_load_config_file)
    except FileNotFoundError as err:
        raise ConfigEntryError(
            f"Configuration file '{_config_file_path}' is not present!"
        ) from err
    except yaml.YAMLError as err:
        raise ConfigEntryError(
            f"Configuration file '{_config_file_path}' is not valid YAML: {err}"
        ) from err

    try:
        _validated_config = config_schema(_raw_config)
    except Invalid as err:
        raise ConfigEntryError(
            f"Configuration file '{_config_file_path}' is invalid: {err}"
        ) from err

    if entry.data[CONF_MAC] not in _validated_config:
        raise ConfigEntryError(
            f"Gateway with MAC {entry.data[CONF_MAC]} is not configured "
            f"in {_config_file_path}"
        )
    _platforms_config = _validated_config[entry.data[CONF_MAC]][CONF_PLATFORMS]

    # Migrating the config entry's unique_id if it was not formated to the recommended hass standard
    if entry.unique_id != dr.format_mac(entry.unique_id):
        hass.config_entries.async_update_entry(
            entry, unique_id=dr.format_mac(entry.unique_id)
        )
        LOGGER.warning("Migrating config entry unique_id to %s", entry.unique_id)

    gateway_handler = MyHOMEGatewayHandler(
        hass=hass, config_entry=entry, generate_events=_generate_events
    )

    try:
        tests_results = await gateway_handler.test()
    except (OSError, EOFError, TimeoutError) as err:
        # Transient connection failures: the gateway may not be ready yet right
        # after a reboot/power-cycle (it accepts the TCP connection then closes
        # it during negotiation -> asyncio.IncompleteReadError, a subclass of
        # EOFError). Raising ConfigEntryNotReady lets HA retry the setup
        # automatically with backoff instead of failing hard and requiring a
        # manual reload. (ConnectionError is a subclass of OSError.)
        raise ConfigEntryNotReady(
            f"Gateway at {gateway_handler.gateway.host} is not ready yet; will retry."
        ) from err

    # A password problem is permanent and must be handled with a reauth flow,
    # never retried in a loop. Raising ConfigEntryAuthFailed lets HA start
    # (and deduplicate) the reauth flow and flag the entry properly, instead
    # of spawning the flow by hand and failing the setup with a generic error.
    if tests_results is not None and not tests_results["Success"] and tests_results[
        "Message"
    ] in ("password_error", "password_required"):
        raise ConfigEntryAuthFailed(
            f"Gateway authentication failed: {tests_results['Message']}"
        )

    # Any other negotiation failure (including test() returning None, which the
    # library may do on a refused/EOF connection) is treated as transient ->
    # retry rather than give up.
    if tests_results is None or not tests_results["Success"]:
        raise ConfigEntryNotReady(
            f"Gateway at {gateway_handler.gateway.host} did not negotiate "
            "a session; will retry."
        )

    # Typed per-entry state: platforms and entities read from here, nothing is
    # shared through hass.data any more. Must be set BEFORE forwarding the
    # platform setups.
    entry.runtime_data = MyHomeRuntimeData(
        gateway_handler=gateway_handler,
        platforms_config=_platforms_config,
    )

    _command_worker_count = (
        int(entry.options[CONF_WORKER_COUNT])
        if CONF_WORKER_COUNT in entry.options
        else 1
    )

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    gateway_device_entry = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, entry.data[CONF_MAC])},
        identifiers={(DOMAIN, gateway_handler.unique_id)},
        manufacturer=gateway_handler.manufacturer,
        name=gateway_handler.name,
        model=gateway_handler.model,
        sw_version=gateway_handler.firmware,
    )
    gateway_handler.device_registry_id = gateway_device_entry.id

    # Long-running workers as tracked background tasks tied to the config entry:
    # HA cancels them automatically on unload/reload (no lingering tasks).
    # Start consumers before forwarding platforms: entity async_update methods
    # enqueue their initial status requests during setup, and a bounded queue
    # must always have an active consumer to avoid deadlocking large installs.
    gateway_handler.listening_worker = entry.async_create_background_task(
        hass,
        gateway_handler.listening_loop(),
        name=f"myhome-{entry.data[CONF_MAC]}-listener",
    )
    for i in range(_command_worker_count):
        gateway_handler.sending_workers.append(
            entry.async_create_background_task(
                hass,
                gateway_handler.sending_loop(i),
                name=f"myhome-{entry.data[CONF_MAC]}-sender-{i}",
            )
        )

    await hass.config_entries.async_forward_entry_setups(
        entry, list(_platforms_config.keys())
    )

    # Pruning lose entities and devices from the registry
    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    entities_to_be_removed = []
    devices_to_be_removed = [
        device_entry.id
        for device_entry in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        )
        # CEN/CEN+ controls are stateless: they own no entity by design, so the
        # "no entities left -> remove" rule below would wipe them at every
        # restart. They are discovered by activation and must survive.
        if not _is_scenario_control(device_entry)
    ]

    configured_entities = []

    # Expected unique_ids are derived from the validated config alone (the
    # old code read them from the runtime registrations the entities used to
    # leave in a shared dict, which no longer exists):
    # - button devices always spawn a -disable and an -enable entity;
    # - power/energy sensors: the schema pre-fills CONF_ENTITIES with one key
    #   per entity (power, daily-energy, ...) -> suffixed unique_ids;
    # - other sensors and binary sensors are suffixed with their device class;
    # - everything else (light/switch/cover/climate) is one entity per device.
    _mac = entry.data[CONF_MAC]
    for _platform, _devices in _platforms_config.items():
        for _device, _device_config in _devices.items():
            if _platform == BUTTON:
                configured_entities.append(f"{_mac}-{_device}-disable")
                configured_entities.append(f"{_mac}-{_device}-enable")
            elif _device_config.get(CONF_ENTITIES):
                configured_entities.extend(
                    f"{_mac}-{_device}-{_entity_name}"
                    for _entity_name in _device_config[CONF_ENTITIES]
                )
            elif _platform in (SENSOR, BINARY_SENSOR) and _device_config.get(
                CONF_DEVICE_CLASS
            ):
                configured_entities.append(
                    f"{_mac}-{_device}-{_device_config[CONF_DEVICE_CLASS]}"
                )
            else:
                configured_entities.append(f"{_mac}-{_device}")

    for entity_entry in entity_entries:
        if entity_entry.unique_id in configured_entities:
            if entity_entry.device_id in devices_to_be_removed:
                devices_to_be_removed.remove(entity_entry.device_id)
            continue
        entities_to_be_removed.append(entity_entry.entity_id)

    for enity_id in entities_to_be_removed:
        entity_registry.async_remove(enity_id)

    if gateway_device_entry.id in devices_to_be_removed:
        devices_to_be_removed.remove(gateway_device_entry.id)

    for device_id in devices_to_be_removed:
        if (
            len(
                er.async_entries_for_device(
                    entity_registry, device_id, include_disabled_entities=True
                )
            )
            == 0
        ):
            device_registry.async_remove_device(device_id)

    # Reload the entry whenever its data or options change from the UI, so
    # worker_count / file_path / generate_events take effect immediately.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: MyHomeConfigEntry) -> None:
    """Reload the config entry when its data or options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MyHomeConfigEntry) -> bool:
    """Unload a config entry."""

    LOGGER.info("Unloading MyHome entry.")

    platforms = list(entry.runtime_data.platforms_config.keys())
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    # The services are registered once in async_setup and shared by all
    # gateways: they must NOT be removed when a single entry unloads.

    # Signal the loops to stop; the background tasks created via
    # entry.async_create_background_task are cancelled by HA on unload.
    await entry.runtime_data.gateway_handler.close_listener()

    return unload_ok
