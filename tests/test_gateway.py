"""Regression tests for gateway lifecycle, queueing and aggregate routing."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.const import (
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_MAC,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
)
from OWNd.message import OWNAutomationEvent, OWNLightingCommand, OWNLightingEvent

from custom_components.myhome.const import (
    CONF_DEVICE_TYPE,
    CONF_FIRMWARE,
    CONF_MANUFACTURER,
    CONF_MANUFACTURER_URL,
    CONF_SSDP_LOCATION,
    CONF_SSDP_ST,
    CONF_UDN,
)
from custom_components.myhome.gateway import (
    SEND_QUEUE_MAXSIZE,
    MyHOMEGatewayHandler,
)


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def async_fire(self, event_type: str, event_data: dict) -> None:
        self.events.append((event_type, event_data))


class _Hass:
    def __init__(self) -> None:
        self.bus = _Bus()

    def async_create_task(self, coroutine) -> None:
        # Aggregate light area/general messages schedule a delayed status poll.
        # Routing is the subject of these tests, so dispose of that unrelated
        # coroutine without running it.
        coroutine.close()


def _handler() -> MyHOMEGatewayHandler:
    entry = SimpleNamespace(
        entry_id="test-entry",
        data={
            CONF_HOST: "192.0.2.1",
            CONF_PORT: 20000,
            CONF_PASSWORD: "12345",
            CONF_MAC: "00:11:22:33:44:55",
            CONF_SSDP_LOCATION: "http://192.0.2.1/device.xml",
            CONF_SSDP_ST: "upnp:rootdevice",
            CONF_DEVICE_TYPE: "urn:test",
            CONF_FRIENDLY_NAME: "Test gateway",
            CONF_MANUFACTURER: "BTicino S.p.A.",
            CONF_MANUFACTURER_URL: "https://example.invalid",
            CONF_NAME: "MH201",
            CONF_FIRMWARE: "1.0",
            CONF_UDN: "uuid:test",
        },
    )
    return MyHOMEGatewayHandler(_Hass(), entry)


class GatewayLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_starts_unavailable_with_bounded_command_queue(self) -> None:
        handler = _handler()

        self.assertFalse(handler.available)
        self.assertFalse(handler.is_connected)
        self.assertEqual(handler.send_buffer.maxsize, SEND_QUEUE_MAXSIZE)

    async def test_initial_failure_does_not_signal_ready_then_reconnects(self) -> None:
        handler = _handler()
        initial_attempt_finished = asyncio.Event()
        allow_reconnect = asyncio.Event()
        reconnected = asyncio.Event()
        release_listener = asyncio.Event()

        class _EventSession:
            def __init__(self, *, on_state_change, **_kwargs) -> None:
                self._on_state_change = on_state_change
                self.is_connected = False

            async def connect(self):
                initial_attempt_finished.set()
                return

            async def get_next(self):
                await allow_reconnect.wait()
                self.is_connected = True
                self._on_state_change(True)
                reconnected.set()
                await release_listener.wait()
                handler._terminate_listener = True
                return

            async def close(self) -> None:
                return None

        with (
            patch(
                "custom_components.myhome.gateway.OWNEventSession", _EventSession
            ),
            patch("custom_components.myhome.gateway.async_dispatcher_send"),
        ):
            listener = asyncio.create_task(handler.listening_loop())
            await initial_attempt_finished.wait()
            await asyncio.sleep(0)
            self.assertFalse(handler._event_session_ready.is_set())
            self.assertFalse(handler.available)

            allow_reconnect.set()
            await reconnected.wait()
            self.assertTrue(handler._event_session_ready.is_set())
            self.assertTrue(handler.available)
            self.assertTrue(handler.is_connected)

            release_listener.set()
            await listener

        self.assertFalse(handler._event_session_ready.is_set())
        self.assertFalse(handler.is_connected)

    async def test_full_queue_applies_backpressure_without_dropping(self) -> None:
        handler = _handler()
        placeholder = {
            "message": OWNLightingCommand.status("01"),
            "is_status_request": True,
        }
        for _ in range(SEND_QUEUE_MAXSIZE):
            handler.send_buffer.put_nowait(placeholder)

        pending_send = asyncio.create_task(
            handler.send(OWNLightingCommand.switch_on("01"))
        )
        await asyncio.sleep(0)

        self.assertFalse(pending_send.done())
        self.assertEqual(handler.send_buffer.qsize(), SEND_QUEUE_MAXSIZE)

        handler.send_buffer.get_nowait()
        handler.send_buffer.task_done()
        await pending_send

        self.assertEqual(handler.send_buffer.qsize(), SEND_QUEUE_MAXSIZE)

    async def test_task_done_is_balanced_when_send_raises(self) -> None:
        handler = _handler()
        handler._event_session_ready.set()
        await handler.send(OWNLightingCommand.switch_on("01"))

        class _CommandSession:
            is_connected = True

            def __init__(self, **_kwargs) -> None:
                pass

            async def connect(self):
                return {"Success": True, "Message": None}

            async def send(self, **_kwargs) -> None:
                handler._terminate_sender = True
                raise RuntimeError("test send failure")

            async def close(self) -> None:
                return None

        with patch(
            "custom_components.myhome.gateway.OWNCommandSession", _CommandSession
        ):
            await handler.sending_loop(0)

        await asyncio.wait_for(handler.send_buffer.join(), timeout=0.1)
        self.assertEqual(handler.send_buffer.qsize(), 0)


class AggregateRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_general_area_and_group_keep_bus_events_and_dispatch(self) -> None:
        handler = _handler()
        messages = iter(
            [
                OWNLightingEvent("*1*1*#7##"),
                OWNAutomationEvent("*2*1*0##"),
                OWNAutomationEvent("*2*2*1##"),
                OWNAutomationEvent("*2*0*#7##"),
            ]
        )

        class _EventSession:
            def __init__(self, *, on_state_change, **_kwargs) -> None:
                self._on_state_change = on_state_change
                self.is_connected = False

            async def connect(self):
                self.is_connected = True
                self._on_state_change(True)
                return {"Success": True, "Message": None}

            async def get_next(self):
                message = next(messages)
                if str(message) == "*2*0*#7##":
                    handler._terminate_listener = True
                return message

            async def close(self) -> None:
                return None

        dispatched: list[tuple[str, object]] = []

        with (
            patch(
                "custom_components.myhome.gateway.OWNEventSession", _EventSession
            ),
            patch(
                "custom_components.myhome.gateway.async_dispatcher_send",
                side_effect=lambda _hass, signal, message=None: dispatched.append(
                    (signal, message)
                ),
            ),
        ):
            await handler.listening_loop()

        dispatched_signals = {signal for signal, _message in dispatched}
        self.assertIn(handler.entity_signal("1-#7"), dispatched_signals)
        self.assertIn(handler.entity_signal("2-0"), dispatched_signals)
        self.assertIn(handler.entity_signal("2-1"), dispatched_signals)
        self.assertIn(handler.entity_signal("2-#7"), dispatched_signals)

        bus_events = {event_type for event_type, _data in handler.hass.bus.events}
        self.assertIn("myhome_group_light_event", bus_events)
        self.assertIn("myhome_general_automation_event", bus_events)
        self.assertIn("myhome_area_automation_event", bus_events)
        self.assertIn("myhome_group_automation_event", bus_events)


if __name__ == "__main__":
    unittest.main()
