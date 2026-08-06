"""Regression tests for climate state handling."""

import asyncio
import unittest
from types import SimpleNamespace

from homeassistant.components.climate.const import HVACMode
from OWNd.message import OWNHeatingEvent

from custom_components.myhome.climate import MyHOMEClimate


def _climate_entity() -> MyHOMEClimate:
    entity = MyHOMEClimate.__new__(MyHOMEClimate)
    entity._gateway_handler = SimpleNamespace(log_id="[test gateway]")
    entity._target_temperature = None
    entity._local_offset = None
    entity._local_offset_raw = None
    entity._local_control_state = None
    entity._local_target_temperature = None
    entity.async_schedule_update_ha_state = lambda: None
    return entity


class ClimateStateTest(unittest.TestCase):
    def test_central_and_local_targets_remain_distinct(self):
        entity = _climate_entity()

        entity.handle_event(OWNHeatingEvent("*#4*3*14*0250*3##"))
        entity.handle_event(OWNHeatingEvent("*#4*3*12*0350*3##"))

        self.assertEqual(entity._target_temperature, 25.0)
        self.assertEqual(entity._local_target_temperature, 35.0)
        self.assertEqual(entity.target_temperature, 35.0)

    def test_special_dim13_state_does_not_overwrite_target(self):
        entity = _climate_entity()
        entity._target_temperature = 25.0
        entity._local_target_temperature = 35.0

        entity.handle_event(OWNHeatingEvent("*#4*3*13*6##"))

        self.assertIsNone(entity._local_offset)
        self.assertEqual(entity._local_offset_raw, "6")
        self.assertEqual(entity._local_control_state, "local_override")
        self.assertEqual(entity._target_temperature, 25.0)
        self.assertEqual(entity._local_target_temperature, 35.0)

    def test_update_requests_general_and_valve_status(self):
        commands = []

        async def send_status_request(command):
            commands.append(str(command))

        entity = _climate_entity()
        entity._where = "3"
        entity._gateway_handler = SimpleNamespace(
            log_id="[test gateway]", send_status_request=send_status_request
        )

        asyncio.run(entity.async_update())

        self.assertEqual(commands, ["*#4*3##", "*#4*3*19##"])

    def test_set_temperature_converts_numeric_offset_to_central_target(self):
        commands = []

        async def send(command):
            commands.append(str(command))

        entity = _climate_entity()
        entity._where = "3"
        entity._standalone = False
        entity._attr_hvac_mode = HVACMode.HEAT
        entity._local_offset = 1
        entity._gateway_handler = SimpleNamespace(
            log_id="[test gateway]", send=send
        )

        asyncio.run(entity.async_set_temperature(temperature=35.0))

        self.assertEqual(commands, ["*#4*#3*#14*0340*1##"])


if __name__ == "__main__":
    unittest.main()
