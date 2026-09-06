"""Regression tests for MyHOME YAML validation and platform setup."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.myhome import cover, light, switch
from custom_components.myhome.const import (
    CONF_DEVICE_MODEL,
    CONF_ENTITIES,
    CONF_ENTITY_NAME,
    CONF_ICON,
    CONF_ICON_ON,
    CONF_PLATFORMS,
    CONF_WHO,
)
from custom_components.myhome.compat import device_via_kwargs
from custom_components.myhome.validate import config_schema


class _Gateway:
    mac = "00:03:50:ae:9b:9c"
    unique_id = mac
    device_registry_id = "gateway-device-id"
    available = True


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.validated = config_schema(
            {
                "gateway": {
                    "mac": _Gateway.mac,
                    "light": {
                        "kitchen": {"where": "03", "name": "Kitchen"}
                    },
                    "switch": {
                        "outlet": {"where": "20", "name": "Outlet"}
                    },
                    "cover": {
                        "shutter": {"where": "0110", "name": "Shutter"}
                    },
                    "binary_sensor": {
                        "motion": {
                            "where": "1",
                            "name": "Motion",
                            "class": BinarySensorDeviceClass.MOTION,
                        }
                    },
                    "sensor": {
                        "meter": {
                            "where": "19",
                            "name": "Meter",
                            "class": SensorDeviceClass.POWER,
                        }
                    },
                }
            }
        )
        self.platforms = self.validated[_Gateway.mac][CONF_PLATFORMS]

    def test_nested_platform_schemas_run_their_normalization(self):
        self.assertIn("1-03", self.platforms["light"])
        self.assertIn("1-20", self.platforms["switch"])
        self.assertIn("2-0110", self.platforms["cover"])
        self.assertIn("25-1", self.platforms["binary_sensor"])
        self.assertIn("18-19", self.platforms["sensor"])

        light_config = self.platforms["light"]["1-03"]
        self.assertIsNone(light_config[CONF_ENTITY_NAME])
        self.assertIsNone(light_config[CONF_ICON])
        self.assertIsNone(light_config[CONF_ICON_ON])
        self.assertIsNone(light_config[CONF_DEVICE_MODEL])
        self.assertEqual(light_config[CONF_ENTITIES], {})
        self.assertEqual(
            self.platforms["sensor"]["18-19"][CONF_WHO], "18"
        )

    def test_minimal_light_switch_and_cover_setup(self):
        runtime_data = SimpleNamespace(
            platforms_config=self.platforms,
            gateway_handler=_Gateway(),
        )
        entry = SimpleNamespace(runtime_data=runtime_data)

        for platform in (light, switch, cover):
            entities = []
            asyncio.run(platform.async_setup_entry(None, entry, entities.extend))
            self.assertEqual(len(entities), 1)
            self.assertEqual(
                entities[0].device_info["via_device_id"], "gateway-device-id"
            )
            self.assertNotIn("via_device", entities[0].device_info)

    def test_legacy_parent_device_compatibility(self):
        with patch("custom_components.myhome.compat._SUPPORTS_VIA_DEVICE_ID", False):
            self.assertEqual(
                device_via_kwargs("gateway-device-id", ("myhome", _Gateway.mac)),
                {"via_device": ("myhome", _Gateway.mac)},
            )


if __name__ == "__main__":
    unittest.main()
