"""Tests for MyHOME HA platform entities handle_event methods using lightweight mocking."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.myhome.ownd.message import (
    OWNHeatingEvent, OWNHeatingCommand,
    OWNEvent, OWNDryContactEvent, OWNLightingEvent
)

from homeassistant.components.climate.const import (
    HVACMode,
    HVACAction,
)

@pytest.fixture
def mock_hass():
    """Create a minimal mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.async_create_task = MagicMock()
    return hass

@pytest.fixture
def mock_gateway():
    """Create a minimal mock gateway handler."""
    gw = MagicMock()
    gw.mac = "00:03:50:00:12:34"
    gw.unique_id = "00:03:50:00:12:34"
    gw.log_id = "[Test Gateway]"
    gw.send = AsyncMock()
    gw.send_status_request = AsyncMock()
    return gw

@pytest.fixture
def mock_entity_base_init():
    with patch("custom_components.myhome.myhome_device.Entity.__init__", return_value=None):
        yield

# ── Climate Entity ─────────────────────────────────────────────────────────

class TestClimateEntity:

    @pytest.fixture
    def climate(self, mock_hass, mock_gateway, mock_entity_base_init):
        from custom_components.myhome.climate import MyHOMEClimate
        c = MyHOMEClimate(
            hass=mock_hass,
            name="Climate 1",
            entity_name="Climate 1",
            device_id="4#01",
            who="4",
            zone="01",
            heating_support=True,
            cooling_support=True,
            fan_support=False,
            standalone=False,
            central=False,
            manufacturer="BTicino",
            model="Thermostat",
            gateway=mock_gateway,
        )
        c.async_schedule_update_ha_state = MagicMock()
        return c

    def test_handle_event_mode_off(self, climate):
        msg = OWNEvent.parse("*4*303*01##")
        climate.handle_event(msg)
        assert climate._attr_hvac_mode == HVACMode.OFF
        assert climate._attr_hvac_action == HVACAction.OFF
        climate.async_schedule_update_ha_state.assert_called()

    def test_handle_event_mode_heat(self, climate):
        msg = OWNEvent.parse("*4*1*01##")
        climate.handle_event(msg)
        assert climate._attr_hvac_mode == HVACMode.HEAT
        assert climate._attr_hvac_action == HVACAction.HEATING

    def test_handle_event_mode_cool(self, climate):
        msg = OWNEvent.parse("*4*0*01##")
        climate.handle_event(msg)
        assert climate._attr_hvac_mode == HVACMode.COOL
        assert climate._attr_hvac_action == HVACAction.COOLING

    def test_handle_event_main_temperature(self, climate):
        msg = OWNEvent.parse("*#4*01*0*0225##")
        climate.handle_event(msg)
        assert climate._attr_current_temperature == 22.5

    def test_handle_event_target_temperature(self, climate):
        msg = OWNEvent.parse("*#4*01*14*0210##")
        climate.handle_event(msg)
        assert climate._attr_target_temperature == 21.0

    @pytest.mark.asyncio
    async def test_async_set_temperature(self, climate):
        await climate.async_set_temperature(temperature=23.5)
        climate._gateway_handler.send.assert_called_once()
        sent_cmd = climate._gateway_handler.send.call_args[0][0]
        assert "0235" in str(sent_cmd)

    @pytest.mark.asyncio
    async def test_async_set_hvac_mode(self, climate):
        await climate.async_set_hvac_mode(HVACMode.HEAT)
        climate._gateway_handler.send.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_async_update(self, climate):
        await climate.async_update()
        climate._gateway_handler.send_status_request.assert_called()

# ── Binary Sensor Entities ──────────────────────────────────────────────────

class TestBinarySensorEntity:

    @pytest.fixture
    def dry_contact(self, mock_hass, mock_gateway, mock_entity_base_init):
        from custom_components.myhome.binary_sensor import MyHOMEDryContactBinarySensor
        s = MyHOMEDryContactBinarySensor(
            hass=mock_hass,
            name="Door",
            entity_name="Door",
            device_id="25#31",
            who="25",
            where="31",
            device_class="door",
            inverted=False,
            manufacturer="B",
            model="M",
            gateway=mock_gateway,
        )
        s.async_schedule_update_ha_state = MagicMock()
        return s

    def test_dry_contact_handle_event(self, dry_contact):
        msg = OWNEvent.parse("*25*31#1*31##") # Open
        dry_contact.handle_event(msg)
        assert dry_contact._attr_is_on is True

        msg2 = OWNEvent.parse("*25*31#0*31##") # Close
        dry_contact.handle_event(msg2)
        assert dry_contact._attr_is_on is False

# ── Sensor Entities ────────────────────────────────────────────────────────

class TestSensorEntity:

    @pytest.fixture
    def power_sensor(self, mock_hass, mock_gateway, mock_entity_base_init):
        from custom_components.myhome.sensor import MyHOMEPowerSensor
        s = MyHOMEPowerSensor(
            hass=mock_hass,
            name="Power",
            entity_name="Power",
            device_id="18#51",
            who="18",
            where="51",
            device_class="power",
            manufacturer="B",
            model="M",
            gateway=mock_gateway,
        )
        s.async_schedule_update_ha_state = MagicMock()
        return s

    def test_power_sensor_handle_event(self, power_sensor):
        msg = OWNEvent.parse("*18*51*113*114*115##")
        power_sensor.handle_event(msg)
        assert power_sensor._attr_native_value == 113.0
        assert power_sensor._attr_extra_state_attributes["voltage"] == 115.0

    @pytest.mark.asyncio
    async def test_async_update(self, power_sensor):
        await power_sensor.async_update()
        power_sensor._gateway_handler.send_status_request.assert_called()

# ── Gateway Connection ──────────────────────────────────────────────────────

class TestGatewayConnection:
    @pytest.mark.asyncio
    async def test_test_connection_dns_failure(self):
        from custom_components.myhome.ownd.connection import OWNSession
        with patch("asyncio.open_connection", side_effect=OSError("DNS fail")):
            session = OWNSession(address="invalid_host", port=20000, password="123")
            response = await session.test_connection()
            assert response["Success"] is False
            assert response["Message"] == "connection_refused"
