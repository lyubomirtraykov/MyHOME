"""Regression tests for legacy config-entry migration."""

import asyncio
import unittest
from types import SimpleNamespace

from homeassistant.const import CONF_FRIENDLY_NAME, CONF_NAME

from custom_components.myhome import async_migrate_entry
from custom_components.myhome.compat import first_scalar
from custom_components.myhome.const import (
    CONF_MANUFACTURER,
    CONF_MANUFACTURER_URL,
)


class _ConfigEntries:
    def __init__(self):
        self.updated = None

    def async_update_entry(self, entry, **kwargs):
        self.updated = (entry, kwargs)


class MigrationTest(unittest.TestCase):
    def test_first_scalar_handles_nested_and_empty_legacy_values(self):
        self.assertEqual(first_scalar([["BTicino S.p.A."]]), "BTicino S.p.A.")
        self.assertEqual(first_scalar([], "fallback"), "fallback")
        self.assertEqual(first_scalar([None], "fallback"), "fallback")

    def test_version_one_entry_is_migrated_to_scalars(self):
        config_entries = _ConfigEntries()
        hass = SimpleNamespace(config_entries=config_entries)
        entry = SimpleNamespace(
            version=1,
            entry_id="test-entry",
            data={
                CONF_MANUFACTURER: ["BTicino S.p.A."],
                CONF_MANUFACTURER_URL: [None],
                CONF_FRIENDLY_NAME: ["Gateway"],
                CONF_NAME: "MH201",
            },
        )

        result = asyncio.run(async_migrate_entry(hass, entry))

        self.assertTrue(result)
        _, update = config_entries.updated
        self.assertEqual(update["version"], 2)
        self.assertEqual(update["data"][CONF_MANUFACTURER], "BTicino S.p.A.")
        self.assertIsNone(update["data"][CONF_MANUFACTURER_URL])
        self.assertEqual(update["data"][CONF_FRIENDLY_NAME], "Gateway")
        self.assertEqual(update["data"][CONF_NAME], "MH201")


if __name__ == "__main__":
    unittest.main()
