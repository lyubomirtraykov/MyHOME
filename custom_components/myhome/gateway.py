"""Code to handle a MyHome Gateway."""
import asyncio
import contextlib

from homeassistant.const import (
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from OWNd.connection import OWNCommandSession, OWNEventSession, OWNGateway, OWNSession
from OWNd.message import (
    OWNAutomationEvent,
    OWNAuxEvent,
    OWNCENEvent,
    OWNCENPlusEvent,
    OWNCommand,
    OWNDryContactEvent,
    OWNEnergyEvent,
    OWNEvent,
    OWNGatewayCommand,
    OWNGatewayEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNLightingCommand,
    OWNLightingEvent,
    OWNMessage,
)

from .const import (
    CEN_KIND,
    CEN_PLUS_KIND,
    CONF_DEVICE_TYPE,
    CONF_FIRMWARE,
    CONF_LONG_PRESS,
    CONF_LONG_RELEASE,
    CONF_MANUFACTURER,
    CONF_MANUFACTURER_URL,
    CONF_SHORT_PRESS,
    CONF_SHORT_RELEASE,
    CONF_SSDP_LOCATION,
    CONF_SSDP_ST,
    CONF_UDN,
    DOMAIN,
    LOGGER,
    SCENARIO_CONTROL_MODELS,
    SCENARIO_CONTROL_NAMES,
    scenario_control_id,
)
from .compat import first_scalar

# Max time a command worker waits for the event session to come up before it
# gives up (the OWNd connect() already retries internally with backoff).
EVENT_READY_TIMEOUT = 120

# An event-session outage must persist this long AFTER OWNd has already
# exhausted its own reconnection attempts (~13-40s) before the entities are
# marked unavailable. Routine ~58min session recycles recover in <1s and never
# emit a state-change, so they never reach this. Total perceived outage before
# entities go unavailable is roughly AVAILABILITY_GRACE + OWNd's give-up window.
AVAILABILITY_GRACE = 60


class MyHOMEGatewayHandler:
    """Manages a single MyHOME Gateway."""

    def __init__(self, hass, config_entry, generate_events=False):
        build_info = {
            "address": config_entry.data[CONF_HOST],
            "port": config_entry.data[CONF_PORT],
            "password": config_entry.data[CONF_PASSWORD],
            "ssdp_location": first_scalar(config_entry.data[CONF_SSDP_LOCATION]),
            "ssdp_st": first_scalar(config_entry.data[CONF_SSDP_ST]),
            "deviceType": first_scalar(config_entry.data[CONF_DEVICE_TYPE]),
            "friendlyName": first_scalar(config_entry.data[CONF_FRIENDLY_NAME]),
            "manufacturer": first_scalar(
                config_entry.data[CONF_MANUFACTURER], "BTicino S.p.A."
            ),
            "manufacturerURL": first_scalar(
                config_entry.data[CONF_MANUFACTURER_URL]
            ),
            "modelName": first_scalar(config_entry.data[CONF_NAME]),
            "modelNumber": first_scalar(config_entry.data[CONF_FIRMWARE]),
            "serialNumber": config_entry.data[CONF_MAC],
            "UDN": first_scalar(config_entry.data[CONF_UDN]),
        }
        self.hass = hass
        self.config_entry = config_entry
        self.generate_events = generate_events
        self.gateway = OWNGateway(build_info)
        self._terminate_listener = False
        self._terminate_sender = False
        self.is_connected = False
        self._available = True
        self._unavailable_timer = None
        self._event_session_ready = asyncio.Event()  # Nuovo evento per sincronizzazione
        self.listening_worker: asyncio.Task | None = None
        self.sending_workers: list[asyncio.Task] = []
        self.send_buffer: asyncio.Queue[dict] = asyncio.Queue()
        # CEN/CEN+ controls already added to the device registry this session.
        self._known_scenario_controls: set[tuple[str, int]] = set()

    @property
    def mac(self) -> str:
        return self.gateway.serial

    @property
    def unique_id(self) -> str:
        return self.mac

    @property
    def log_id(self) -> str:
        return self.gateway.log_id

    @property
    def manufacturer(self) -> str:
        return self.gateway.manufacturer

    @property
    def name(self) -> str:
        return f"{self.gateway.model_name} Gateway"

    @property
    def model(self) -> str:
        return self.gateway.model_name

    @property
    def firmware(self) -> str:
        return self.gateway.firmware

    @property
    def available(self) -> bool:
        """Filtered availability the entities derive their own from."""
        return self._available

    @property
    def availability_signal(self) -> str:
        """Dispatcher signal fired when the gateway availability changes."""
        return f"{DOMAIN}_{self.mac}_availability"

    def entity_signal(self, device_id: str) -> str:
        """Dispatcher signal carrying bus messages addressed to one device.

        Every entity of the device subscribes to it in async_added_to_hass;
        the listener fires it with the parsed OWNMessage as payload.
        """
        return f"{DOMAIN}_{self.mac}_{device_id}"

    @callback
    def _register_scenario_control(self, kind: str, object_id: int) -> None:
        """Register a CEN/CEN+ control in the device registry on first use.

        These controls carry no state and therefore have no entities: they exist
        purely so their buttons can be picked as device triggers in the
        automation UI. Discovery is by activation — press a button once and the
        control appears.
        """
        key = (kind, object_id)
        if key in self._known_scenario_controls:
            return
        self._known_scenario_controls.add(key)
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            identifiers={(DOMAIN, scenario_control_id(self.mac, kind, object_id))},
            name=f"{SCENARIO_CONTROL_NAMES[kind]} {object_id}",
            manufacturer=self.manufacturer,
            model=SCENARIO_CONTROL_MODELS[kind],
            via_device=(DOMAIN, self.unique_id),
        )
        LOGGER.info(
            "%s Registered %s control %s (press its buttons to use them as "
            "device triggers).",
            self.log_id,
            SCENARIO_CONTROL_NAMES[kind],
            object_id,
        )

    @callback
    def _on_connection_state_change(self, connected: bool) -> None:
        """Invoked by OWNd (in the event loop) on real connection transitions.

        OWNd only flips to False after exhausting its own reconnection attempts,
        so routine ~58min recycles never reach here. We add a grace period on
        top: only a *sustained* outage marks the entities unavailable, and a
        recovery within the grace window is completely silent.
        """
        if connected:
            if self._unavailable_timer is not None:
                self._unavailable_timer()
                self._unavailable_timer = None
            if not self._available:
                self._available = True
                LOGGER.info("%s Gateway available again.", self.log_id)
                self._notify_availability()
        elif self._unavailable_timer is None and self._available:
            LOGGER.warning(
                "%s Gateway connection lost; marking unavailable in %ss "
                "if not recovered.",
                self.log_id,
                AVAILABILITY_GRACE,
            )
            self._unavailable_timer = async_call_later(
                self.hass, AVAILABILITY_GRACE, self._mark_unavailable
            )

    @callback
    def _mark_unavailable(self, _now) -> None:
        """Grace period elapsed without recovery: entities go unavailable."""
        self._unavailable_timer = None
        if self._available:
            self._available = False
            LOGGER.warning(
                "%s Gateway unavailable (outage exceeded %ss).",
                self.log_id,
                AVAILABILITY_GRACE,
            )
            self._notify_availability()

    @callback
    def _notify_availability(self) -> None:
        """Tell every entity bound to this gateway to re-render availability."""
        async_dispatcher_send(self.hass, self.availability_signal)

    async def test(self) -> dict:
        return await OWNSession(gateway=self.gateway, logger=LOGGER).test_connection()

    async def listening_loop(self):
        self._terminate_listener = False

        LOGGER.debug("%s Creating listening worker.", self.log_id)

        _event_session = OWNEventSession(
            gateway=self.gateway,
            logger=LOGGER,
            on_state_change=self._on_connection_state_change,
        )
        try:
            await _event_session.connect()
        except Exception:
            # Never leave the command workers blocked forever on a readiness
            # signal that will never arrive: surface the failure (the task ends,
            # and the entry-level retry logic can take over) instead of dying
            # silently with the event still unset.
            self.is_connected = False
            LOGGER.exception(
                "%s Event session could not be established.", self.log_id
            )
            raise

        self.is_connected = True
        self._event_session_ready.set()  # Event session up: command sessions may start.
        LOGGER.debug(
            "%s Event session ready, command sessions can now start.", self.log_id
        )

        try:
            while not self._terminate_listener:
                message = await _event_session.get_next()
                try:
                    LOGGER.debug("%s Message received: `%s`", self.log_id, message)

                    if self.generate_events:
                        if isinstance(message, OWNMessage):
                            _event_content = {"gateway": str(self.gateway.host)}
                            _event_content.update(message.event_content)
                            self.hass.bus.async_fire("myhome_message_event", _event_content)
                        elif message is not None:
                        # EOF di routine -> get_next() restituisce None: non è un evento,
                        # non lo immettiamo sul bus (coerente col declassamento a DEBUG del log).
                            self.hass.bus.async_fire("myhome_message_event", {"gateway": str(self.gateway.host), "message": str(message)})

                    if not isinstance(message, OWNMessage):
                        # Expected on a routine session close/reconnect (EOF -> None),
                        # so log at DEBUG: it is not an anomaly.
                        LOGGER.debug(
                            "%s Data received is not a message: `%s`",
                            self.log_id,
                            message,
                        )
                    elif isinstance(message, OWNEnergyEvent):
                        # Every entity of the addressed device is subscribed to
                        # this signal and filters by message type on its own; a
                        # message for an unconfigured device has no subscribers
                        # and dies silently.
                        async_dispatcher_send(
                            self.hass, self.entity_signal(message.entity), message
                        )
                    elif isinstance(
                        message,
                        (
                            OWNLightingEvent,
                            OWNAutomationEvent,
                            OWNDryContactEvent,
                            OWNAuxEvent,
                            OWNHeatingEvent,
                        ),
                    ):
                        if not message.is_translation:
                            is_event = False
                            if isinstance(message, OWNLightingEvent):
                                if message.is_general:
                                    is_event = True
                                    event = "on" if message.is_on else "off"
                                    self.hass.bus.async_fire(
                                        "myhome_general_light_event",
                                        {"message": str(message), "event": event},
                                    )
                                    self.hass.async_create_task(self._delayed_status_request(OWNLightingCommand.status("0")))
                                elif message.is_area:
                                    is_event = True
                                    event = "on" if message.is_on else "off"
                                    self.hass.bus.async_fire(
                                        "myhome_area_light_event",
                                        {
                                            "message": str(message),
                                            "area": message.area,
                                            "event": event,
                                        },
                                    )
                                    self.hass.async_create_task(self._delayed_status_request(OWNLightingCommand.status(message.area)))
                                elif message.is_group:
                                    is_event = True
                                    event = "on" if message.is_on else "off"
                                    self.hass.bus.async_fire(
                                        "myhome_group_light_event",
                                        {
                                            "message": str(message),
                                            "group": message.group,
                                            "event": event,
                                        },
                                    )
                            elif isinstance(message, OWNAutomationEvent):
                                if message.is_general:
                                    is_event = True
                                    if message.is_opening and not message.is_closing:
                                        event = "open"
                                    elif message.is_closing and not message.is_opening:
                                        event = "close"
                                    else:
                                        event = "stop"
                                    self.hass.bus.async_fire(
                                        "myhome_general_automation_event",
                                        {"message": str(message), "event": event},
                                    )
                                elif message.is_area:
                                    is_event = True
                                    if message.is_opening and not message.is_closing:
                                        event = "open"
                                    elif message.is_closing and not message.is_opening:
                                        event = "close"
                                    else:
                                        event = "stop"
                                    self.hass.bus.async_fire(
                                        "myhome_area_automation_event",
                                        {
                                            "message": str(message),
                                            "area": message.area,
                                            "event": event,
                                        },
                                    )
                                elif message.is_group:
                                    is_event = True
                                    if message.is_opening and not message.is_closing:
                                        event = "open"
                                    elif message.is_closing and not message.is_opening:
                                        event = "close"
                                    else:
                                        event = "stop"
                                    self.hass.bus.async_fire(
                                        "myhome_group_automation_event",
                                        {
                                            "message": str(message),
                                            "group": message.group,
                                            "event": event,
                                        },
                                    )
                            if not is_event:
                                # Point-to-point message: deliver to whoever is
                                # subscribed for this device (all its entities,
                                # across platforms). The brightness-preset
                                # follow-up query now lives inside the light
                                # entity's own handler.
                                async_dispatcher_send(
                                    self.hass,
                                    self.entity_signal(message.entity),
                                    message,
                                )

                        else:
                            LOGGER.debug(
                                "%s Ignoring translation message `%s`",
                                self.log_id,
                                message,
                            )
                    elif isinstance(message, OWNHeatingCommand) and message.dimension is not None and message.dimension == 14:
                        where = message.where[1:] if message.where.startswith("#") else message.where
                        LOGGER.debug(
                            "%s Received heating command, sending query to zone %s",
                            self.log_id,
                            where,
                        )
                        await self.send_status_request(OWNHeatingCommand.status(where))
                        await self.send_status_request(
                            OWNHeatingCommand.valves_status(where)
                        )
                    elif isinstance(message, OWNCENPlusEvent):
                        event = None
                        if message.is_short_pressed:
                            event = CONF_SHORT_PRESS
                        elif message.is_held or message.is_still_held:
                            event = CONF_LONG_PRESS
                        elif message.is_released:
                            event = CONF_LONG_RELEASE
                        else:
                            event = None
                        # Register the control as a device the first time it is
                        # used, so its buttons become selectable as device
                        # triggers in the automation UI (no YAML needed).
                        self._register_scenario_control(
                            CEN_PLUS_KIND, int(message.object)
                        )
                        self.hass.bus.async_fire(
                            "myhome_cenplus_event",
                            {
                                "mac": self.mac,
                                "object": int(message.object),
                                "pushbutton": int(message.push_button),
                                "event": event,
                            },
                        )
                        LOGGER.info(
                            "%s %s",
                            self.log_id,
                            message.human_readable_log,
                        )
                    elif isinstance(message, OWNCENEvent):
                        event = None
                        if message.is_pressed:
                            event = CONF_SHORT_PRESS
                        elif message.is_released_after_short_press:
                            event = CONF_SHORT_RELEASE
                        elif message.is_held:
                            event = CONF_LONG_PRESS
                        elif message.is_released_after_long_press:
                            event = CONF_LONG_RELEASE
                        else:
                            event = None
                        self._register_scenario_control(
                            CEN_KIND, int(message.object)
                        )
                        self.hass.bus.async_fire(
                            "myhome_cen_event",
                            {
                                "mac": self.mac,
                                "object": int(message.object),
                                "pushbutton": int(message.push_button),
                                "event": event,
                            },
                        )
                        LOGGER.info(
                            "%s %s",
                            self.log_id,
                            message.human_readable_log,
                        )
                    elif isinstance(message, (OWNGatewayEvent, OWNGatewayCommand)):
                        LOGGER.info(
                            "%s %s",
                            self.log_id,
                            message.human_readable_log,
                        )
                    elif isinstance(message, (OWNEvent, OWNCommand)) and (
                        (message.who is not None and message.who > 1000)
                        or message.dimension == 1000
                    ):
                        # Diagnostic/translation chatter: WHO > 1000 (actuator
                        # status bitmasks) or dimension 1000 (e.g. the frame an
                        # MH201 emits after an advanced shutter positioning,
                        # `*#2*WHERE*#1000#11#001#N*V##`). Routine bus noise,
                        # not worth an INFO "unsupported" entry.
                        # NB: guarded by the isinstance — OWNSignaling has no
                        # who/dimension attributes.
                        LOGGER.debug(
                            "%s Diagnostic message: `%s`",
                            self.log_id,
                            message,
                        )
                    else:
                        LOGGER.info(
                            "%s Unsupported message type: `%s`",
                            self.log_id,
                            message,
                        )
                except Exception:  # pylint: disable=broad-except
                    # A single bad frame (or a bug in one entity's handler)
                    # must never kill the listener: log it and keep listening.
                    LOGGER.exception(
                        "%s Error while dispatching message `%s`; continuing.",
                        self.log_id,
                        message,
                    )

        finally:
            # Runs also on task cancellation (entry unload/reload): always
            # release the socket instead of leaving it to the garbage
            # collector. shield() lets the close complete even while this
            # task is being cancelled.
            self.is_connected = False
            with contextlib.suppress(Exception):
                await asyncio.shield(_event_session.close())
            LOGGER.debug("%s Destroying listening worker.", self.log_id)

    async def sending_loop(self, worker_id: int):
        self._terminate_sender = False

        LOGGER.debug(
            "%s Creating sending worker %s",
            self.log_id,
            worker_id,
        )

        # Wait for the event session to be established before opening the command
        # session: the MH201 cannot negotiate both at the same time. Bounded, so
        # a never-ready event session cannot hang this worker forever.
        LOGGER.debug(
            "%s Worker %s waiting for event session to be ready...",
            self.log_id,
            worker_id,
        )
        try:
            await asyncio.wait_for(
                self._event_session_ready.wait(), timeout=EVENT_READY_TIMEOUT
            )
        except TimeoutError:
            LOGGER.error(
                "%s Worker %s: event session not ready after %ss; aborting worker.",
                self.log_id,
                worker_id,
                EVENT_READY_TIMEOUT,
            )
            return
        LOGGER.debug(
            "%s Worker %s: event session is ready, proceeding with command session.",
            self.log_id,
            worker_id,
        )

        _command_session = OWNCommandSession(gateway=self.gateway, logger=LOGGER)
        try:
            await _command_session.connect()
        except Exception:
            LOGGER.exception(
                "%s Worker %s: command session could not be established.",
                self.log_id,
                worker_id,
            )
            return

        try:
            while not self._terminate_sender:
                task = await self.send_buffer.get()
                LOGGER.debug(
                    "%s Message `%s` was successfully unqueued by worker %s.",
                    self.log_id,
                    task["message"],
                    worker_id,
                )
                await _command_session.send(
                    message=task["message"], is_status_request=task["is_status_request"]
                )
                self.send_buffer.task_done()
        finally:
            # Runs also on task cancellation (entry unload/reload): always
            # release the socket instead of leaving it to the garbage
            # collector. shield() lets the close complete even while this
            # task is being cancelled.
            with contextlib.suppress(Exception):
                await asyncio.shield(_command_session.close())
            LOGGER.debug(
                "%s Destroying sending worker %s",
                self.log_id,
                worker_id,
            )

    async def close_listener(self) -> bool:
        LOGGER.info("%s Closing event listener", self.log_id)
        self._terminate_sender = True
        self._terminate_listener = True
        if self._unavailable_timer is not None:
            self._unavailable_timer()
            self._unavailable_timer = None

        return True

    async def send(self, message: OWNCommand):
        await self.send_buffer.put({"message": message, "is_status_request": False})
        LOGGER.debug(
            "%s Message `%s` was successfully queued.",
            self.log_id,
            message,
        )

    async def send_status_request(self, message: OWNCommand):
        await self.send_buffer.put({"message": message, "is_status_request": True})
        LOGGER.debug(
            "%s Message `%s` was successfully queued.",
            self.log_id,
            message,
        )

    async def _delayed_status_request(self, command):
        await asyncio.sleep(0.1)
        await self.send_status_request(command)
