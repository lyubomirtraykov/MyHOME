""" MyHOME integration. """

import yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from OWNd.message import OWNCommand, OWNGatewayCommand
from voluptuous import Invalid

from .const import (
    ATTR_GATEWAY,
    ATTR_MESSAGE,
    CONF_ENTITIES,
    CONF_ENTITY,
    CONF_FILE_PATH,
    CONF_GENERATE_EVENTS,
    CONF_PLATFORMS,
    CONF_WORKER_COUNT,
    DOMAIN,
    LOGGER,
)
from .gateway import MyHOMEGatewayHandler
from .validate import config_schema, format_mac

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = ["light", "switch", "cover", "climate", "binary_sensor", "sensor"]


async def async_setup(hass, config):
    """Set up the MyHOME component."""
    hass.data[DOMAIN] = {}

    # The services are global, not tied to a single config entry: register
    # them once here, so loading/unloading one gateway can never remove them
    # for another. The target gateway is resolved at call time.

    async def handle_sync_time(call):
        gateway = call.data.get(ATTR_GATEWAY, None)
        if gateway is None:
            gateway = next(iter(hass.data[DOMAIN]), None)
        else:
            mac = format_mac(gateway)
            if mac is None:
                LOGGER.error(
                    "Invalid gateway mac `%s`, could not send time synchronisation message.",
                    gateway,
                )
                return False
            gateway = mac
        timezone = hass.config.time_zone
        if gateway in hass.data[DOMAIN] and CONF_ENTITY in hass.data[DOMAIN][gateway]:
            await hass.data[DOMAIN][gateway][CONF_ENTITY].send(
                OWNGatewayCommand.set_datetime_to_now(timezone)
            )
        else:
            LOGGER.error(
                "Gateway `%s` not found or not loaded, could not send time synchronisation message.",
                gateway,
            )
            return False
        return True

    hass.services.async_register(DOMAIN, "sync_time", handle_sync_time)

    async def handle_send_message(call):
        gateway = call.data.get(ATTR_GATEWAY, None)
        message = call.data.get(ATTR_MESSAGE, None)
        if gateway is None:
            gateway = next(iter(hass.data[DOMAIN]), None)
        else:
            mac = format_mac(gateway)
            if mac is None:
                LOGGER.error(
                    "Invalid gateway mac `%s`, could not send message `%s`.",
                    gateway,
                    message,
                )
                return False
            gateway = mac
        LOGGER.debug("Handling message `%s` to be sent to `%s`", message, gateway)
        if gateway in hass.data[DOMAIN] and CONF_ENTITY in hass.data[DOMAIN][gateway]:
            if message is not None:
                own_message = OWNCommand.parse(message)
                if own_message is not None:
                    if own_message.is_valid:
                        LOGGER.debug(
                            "%s Sending valid OpenWebNet Message: `%s`",
                            hass.data[DOMAIN][gateway][CONF_ENTITY].log_id,
                            own_message,
                        )
                        await hass.data[DOMAIN][gateway][CONF_ENTITY].send(own_message)
                else:
                    LOGGER.error(
                        "Could not parse message `%s`, not sending it.", message
                    )
                    return False
        else:
            LOGGER.error(
                "Gateway `%s` not found or not loaded, could not send message `%s`.",
                gateway,
                message,
            )
            return False
        return True

    hass.services.async_register(DOMAIN, "send_message", handle_send_message)

    if DOMAIN not in config:
        return True

    LOGGER.error("configuration.yaml not supported for this component!")

    return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    if entry.data[CONF_MAC] not in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.data[CONF_MAC]] = {}

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

    if entry.data[CONF_MAC] in _validated_config:
        hass.data[DOMAIN][entry.data[CONF_MAC]] = _validated_config[
            entry.data[CONF_MAC]
        ]
    else:
        raise ConfigEntryError(
            f"Gateway with MAC {entry.data[CONF_MAC]} is not configured "
            f"in {_config_file_path}"
        )

    # Migrating the config entry's unique_id if it was not formated to the recommended hass standard
    if entry.unique_id != dr.format_mac(entry.unique_id):
        hass.config_entries.async_update_entry(
            entry, unique_id=dr.format_mac(entry.unique_id)
        )
        LOGGER.warning("Migrating config entry unique_id to %s", entry.unique_id)

    hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY] = MyHOMEGatewayHandler(
        hass=hass, config_entry=entry, generate_events=_generate_events
    )

    try:
        tests_results = await hass.data[DOMAIN][entry.data[CONF_MAC]][
            CONF_ENTITY
        ].test()
    except (OSError, EOFError, TimeoutError) as err:
        # Transient connection failures: the gateway may not be ready yet right
        # after a reboot/power-cycle (it accepts the TCP connection then closes
        # it during negotiation -> asyncio.IncompleteReadError, a subclass of
        # EOFError). Raising ConfigEntryNotReady lets HA retry the setup
        # automatically with backoff instead of failing hard and requiring a
        # manual reload. (ConnectionError is a subclass of OSError.)
        _host = hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].gateway.host
        hass.data[DOMAIN][entry.data[CONF_MAC]].pop(CONF_ENTITY, None)
        raise ConfigEntryNotReady(
            f"Gateway at {_host} is not ready yet; will retry."
        ) from err

    # A password problem is permanent and must be handled with a reauth flow,
    # never retried in a loop. Raising ConfigEntryAuthFailed lets HA start
    # (and deduplicate) the reauth flow and flag the entry properly, instead
    # of spawning the flow by hand and failing the setup with a generic error.
    if tests_results is not None and not tests_results["Success"] and tests_results[
        "Message"
    ] in ("password_error", "password_required"):
        hass.data[DOMAIN][entry.data[CONF_MAC]].pop(CONF_ENTITY, None)
        raise ConfigEntryAuthFailed(
            f"Gateway authentication failed: {tests_results['Message']}"
        )

    # Any other negotiation failure (including test() returning None, which the
    # library may do on a refused/EOF connection) is treated as transient ->
    # retry rather than give up.
    if tests_results is None or not tests_results["Success"]:
        _host = hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].gateway.host
        hass.data[DOMAIN][entry.data[CONF_MAC]].pop(CONF_ENTITY, None)
        raise ConfigEntryNotReady(
            f"Gateway at {_host} did not negotiate a session; will retry."
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
        identifiers={
            (DOMAIN, hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].unique_id)
        },
        manufacturer=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].manufacturer,
        name=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].name,
        model=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].model,
        sw_version=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].firmware,
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS].keys()
    )

    # Long-running workers as tracked background tasks tied to the config entry:
    # HA cancels them automatically on unload/reload (no lingering tasks).
    _handler = hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY]
    _handler.listening_worker = entry.async_create_background_task(
        hass,
        _handler.listening_loop(),
        name=f"myhome-{entry.data[CONF_MAC]}-listener",
    )
    for i in range(_command_worker_count):
        _handler.sending_workers.append(
            entry.async_create_background_task(
                hass,
                _handler.sending_loop(i),
                name=f"myhome-{entry.data[CONF_MAC]}-sender-{i}",
            )
        )

    # Pruning lose entities and devices from the registry
    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    entities_to_be_removed = []
    devices_to_be_removed = [
        device_entry.id
        for device_entry in device_registry.devices.values()
        if entry.entry_id in device_entry.config_entries
    ]

    configured_entities = []

    for _platform in hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS]:
        for _device in hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS][
            _platform
        ]:
            for _entity_name in hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS][
                _platform
            ][_device][CONF_ENTITIES]:
                if _entity_name != _platform:
                    configured_entities.append(
                        f"{entry.data[CONF_MAC]}-{_device}-{_entity_name}"
                    )  # extrapolating _attr_unique_id out of the entity's place in the config data structure
                else:
                    configured_entities.append(
                        f"{entry.data[CONF_MAC]}-{_device}"
                    )  # extrapolating _attr_unique_id out of the entity's place in the config data structure

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


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when its data or options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    """Unload a config entry."""

    LOGGER.info("Unloading MyHome entry.")

    platforms = list(
        hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS].keys()
    )
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    # The services are registered once in async_setup and shared by all
    # gateways: they must NOT be removed when a single entry unloads.

    gateway_handler = hass.data[DOMAIN][entry.data[CONF_MAC]].pop(CONF_ENTITY)
    del hass.data[DOMAIN][entry.data[CONF_MAC]]

    # Signal the loops to stop; the background tasks created via
    # entry.async_create_background_task are cancelled by HA on unload.
    await gateway_handler.close_listener()

    return unload_ok


