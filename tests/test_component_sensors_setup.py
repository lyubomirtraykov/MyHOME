import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorDeviceClass
import homeassistant.helpers.entity_platform as entity_platform

from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
)

from custom_components.myhome.sensor import async_setup_entry, MyHOMEPowerSensor
from custom_components.myhome.const import (
    DOMAIN,
    CONF_PLATFORMS,
    CONF_ENTITIES,
    CONF_DEVICE_CLASS,
    CONF_DEVICE_MODEL,
    CONF_MANUFACTURER,
    CONF_WHERE,
    CONF_WHO,
    CONF_ENTITY,
)

@pytest.fixture
def mock_config_entry():
    entry = MagicMock()
    entry.data = {
        CONF_MAC: "00:11:22:33:44:55",
    }
    return entry

@pytest.fixture
def mock_hass():
    hass = MagicMock(spec=HomeAssistant)
    
    # Setup standard mocked data structure for the gateway MAC
    hass.data = {
        DOMAIN: {
            "00:11:22:33:44:55": {
                CONF_PLATFORMS: {
                    "sensor": {
                        "sensor_power_1": {
                            CONF_DEVICE_CLASS: SensorDeviceClass.POWER,
                            CONF_ENTITIES: {SensorDeviceClass.POWER: {}},
                            CONF_WHO: "18",
                            CONF_WHERE: "51",
                            CONF_NAME: "Power Sensor",
                            CONF_MANUFACTURER: "Bticino",
                            CONF_DEVICE_MODEL: "Meter",
                        },
                        "sensor_energy_1": {
                            CONF_DEVICE_CLASS: SensorDeviceClass.ENERGY,
                            CONF_ENTITIES: {"total-energy": {}},
                            CONF_WHO: "18",
                            CONF_WHERE: "51",
                            CONF_NAME: "Energy Sensor",
                            CONF_MANUFACTURER: "Bticino",
                            CONF_DEVICE_MODEL: "Meter",
                        }
                    }
                },
                CONF_ENTITY: MagicMock() # Mock Gateway
            }
        }
    }
    return hass

@pytest.mark.asyncio
async def test_async_setup_entry_power_migration(mock_hass, mock_config_entry):
    mock_add_entities = MagicMock()
    
    platform_token = entity_platform.current_platform.set(MagicMock())
    try:
        with patch("custom_components.myhome.sensor.er.async_get") as mock_er_get:
            # Mock entity registry
            mock_registry = MagicMock()
            mock_registry.async_get_entity_id.return_value = "sensor.some_legacy_id"
            mock_er_get.return_value = mock_registry
            
            await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)
            
            # Registry update should be called because we returned an existing legacy ID
            mock_registry.async_update_entity.assert_called_once_with(
                entity_id="sensor.some_legacy_id",
                new_unique_id=f"sensor_power_1-{SensorDeviceClass.POWER}"
            )
            
            # We should have added two entities: 1 Power, 1 Energy
            assert mock_add_entities.call_count == 1
            sensors_added = mock_add_entities.call_args[0][0]
            assert len(sensors_added) == 2
            
            power_sens = [s for s in sensors_added if isinstance(s, MyHOMEPowerSensor)]
            assert len(power_sens) == 1
            assert power_sens[0].name == "Power Sensor Power"
    finally:
        entity_platform.current_platform.reset(platform_token)

@pytest.mark.asyncio
async def test_async_setup_entry_no_migration(mock_hass, mock_config_entry):
    mock_add_entities = MagicMock()
    
    platform_token = entity_platform.current_platform.set(MagicMock())
    try:
        with patch("custom_components.myhome.sensor.er.async_get") as mock_er_get:
            mock_registry = MagicMock()
            # No legacy entity id exists
            mock_registry.async_get_entity_id.return_value = None
            mock_er_get.return_value = mock_registry
            
            await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)
            
            # Registry update should NOT be called
            mock_registry.async_update_entity.assert_not_called()
            
            assert mock_add_entities.call_count == 1
            sensors_added = mock_add_entities.call_args[0][0]
            assert len(sensors_added) == 2
    finally:
        entity_platform.current_platform.reset(platform_token)

@pytest.mark.asyncio
async def test_async_setup_entry_no_platform_data(mock_hass, mock_config_entry):
    # Rip out the "sensor" platform from hass data
    del mock_hass.data[DOMAIN]["00:11:22:33:44:55"][CONF_PLATFORMS]["sensor"]
    
    mock_add_entities = MagicMock()
    
    result = await async_setup_entry(mock_hass, mock_config_entry, mock_add_entities)
    
    assert result is True
    mock_add_entities.assert_not_called()
