"""Tests for OWNHeatingEvent and OWNHeatingCommand protocol translation."""
import pytest
from custom_components.myhome.ownd.message import (
    OWNEvent,
    OWNCommand,
    OWNHeatingEvent,
    OWNHeatingCommand,
    CLIMATE_MODE_OFF,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_AUTO,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_MODE_TARGET,
    MESSAGE_TYPE_MAIN_TEMPERATURE,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    MESSAGE_TYPE_TARGET_TEMPERATURE,
    MESSAGE_TYPE_LOCAL_OFFSET,
    MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE,
    MESSAGE_TYPE_ACTION,
    MESSAGE_TYPE_MAIN_HUMIDITY,
)


class TestHeatingEventParsing:
    """Validate OWNHeatingEvent via OWNEvent.parse factory."""

    def test_mode_off(self):
        msg = OWNEvent.parse("*4*303*1##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_MODE
        assert msg.mode == CLIMATE_MODE_OFF

    def test_mode_heat(self):
        msg = OWNEvent.parse("*4*1*1##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_MODE
        assert msg.mode == CLIMATE_MODE_HEAT

    def test_mode_cool(self):
        msg = OWNEvent.parse("*4*0*1##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_MODE
        assert msg.mode == CLIMATE_MODE_COOL

    def test_mode_auto(self):
        msg = OWNEvent.parse("*4*311*1##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_MODE
        assert msg.mode == CLIMATE_MODE_AUTO

    def test_mode_with_target_temperature(self):
        msg = OWNEvent.parse("*4*1#0215*1##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_MODE_TARGET
        assert msg.set_temperature == 21.5

    def test_main_temperature(self):
        msg = OWNEvent.parse("*#4*1*0*0225##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_MAIN_TEMPERATURE
        assert msg.main_temperature == 22.5

    def test_secondary_temperature(self):
        msg = OWNEvent.parse("*#4*201*0*0200##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
        assert msg.secondary_temperature == [2, 20.0]

    def test_target_temperature(self):
        msg = OWNEvent.parse("*#4*1*14*0210##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
        assert msg.set_temperature == 21.0

    def test_local_offset_zero(self):
        msg = OWNEvent.parse("*#4*1*13*00##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_LOCAL_OFFSET
        assert msg.local_offset == 0

    def test_local_offset_positive(self):
        msg = OWNEvent.parse("*#4*1*13*03##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_LOCAL_OFFSET
        assert msg.local_offset == 3

    def test_local_offset_negative(self):
        msg = OWNEvent.parse("*#4*1*13*13##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_LOCAL_OFFSET
        assert msg.local_offset == -3

    def test_local_set_temperature(self):
        msg = OWNEvent.parse("*#4*1*12*0225##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE
        assert msg.local_set_temperature == 22.5

    def test_valve_status(self):
        msg = OWNEvent.parse("*#4*1*19*1*0##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_ACTION

    def test_humidity(self):
        msg = OWNEvent.parse("*#4*1*60*65##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.message_type == MESSAGE_TYPE_MAIN_HUMIDITY
        assert msg.main_humidity == 65.0

    def test_fan_speed_on(self):
        msg = OWNEvent.parse("*#4*1*11*2##")
        assert isinstance(msg, OWNHeatingEvent)

    def test_fan_speed_off(self):
        msg = OWNEvent.parse("*#4*1*11*4##")
        assert isinstance(msg, OWNHeatingEvent)

    def test_remote_control_disabled(self):
        msg = OWNEvent.parse("*4*20*1##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.mode is None

    def test_remote_control_enabled(self):
        msg = OWNEvent.parse("*4*21*1##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.mode is None

    def test_zone_from_hash_where(self):
        msg = OWNEvent.parse("*#4*#1*0*0225##")
        assert isinstance(msg, OWNHeatingEvent)
        assert msg.zone == 1


class TestHeatingCommandGeneration:
    """Validate OWNHeatingCommand factory methods."""

    def test_status_request(self):
        cmd = OWNHeatingCommand.status("1")
        assert str(cmd) == "*#4*1##"

    def test_get_temperature(self):
        cmd = OWNHeatingCommand.get_temperature("1")
        assert str(cmd) == "*#4*1*0##"

    def test_set_mode_off(self):
        cmd = OWNHeatingCommand.set_mode("1", CLIMATE_MODE_OFF)
        assert cmd is not None
        assert "303" in str(cmd)

    def test_set_mode_auto(self):
        cmd = OWNHeatingCommand.set_mode("1", CLIMATE_MODE_AUTO)
        assert cmd is not None
        assert "311" in str(cmd)

    def test_set_mode_invalid_returns_none(self):
        """Only OFF and AUTO are supported in set_mode."""
        cmd = OWNHeatingCommand.set_mode("1", CLIMATE_MODE_HEAT)
        assert cmd is None

    def test_turn_off(self):
        cmd = OWNHeatingCommand.turn_off("1")
        assert cmd is not None

    def test_set_temperature_heat(self):
        cmd = OWNHeatingCommand.set_temperature("1", 21.5, CLIMATE_MODE_HEAT)
        assert cmd is not None
        assert "0215" in str(cmd)

    def test_set_temperature_cool(self):
        cmd = OWNHeatingCommand.set_temperature("1", 25.0, CLIMATE_MODE_COOL)
        assert cmd is not None
        assert "0250" in str(cmd)

    def test_set_temperature_clamp_low(self):
        cmd = OWNHeatingCommand.set_temperature("1", 2.0, CLIMATE_MODE_HEAT)
        assert cmd is not None
        assert "0050" in str(cmd)

    def test_set_temperature_clamp_high(self):
        cmd = OWNHeatingCommand.set_temperature("1", 45.0, CLIMATE_MODE_HEAT)
        assert cmd is not None
        assert "0400" in str(cmd)

    def test_command_parse_who4(self):
        cmd = OWNCommand.parse("*#4*1##")
        assert isinstance(cmd, OWNHeatingCommand)
