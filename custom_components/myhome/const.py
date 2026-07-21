"""Constants for the MyHome component."""
import logging

LOGGER = logging.getLogger(__package__)
DOMAIN = "myhome"

ATTR_GATEWAY = "gateway"
ATTR_MESSAGE = "message"

CONF = "config"
CONF_ENTITY = "entity"
CONF_ENTITIES = "entities"
CONF_ENTITY_NAME = "entity_name"
CONF_ICON = "icon"
CONF_ICON_ON = "icon_on"
CONF_PLATFORMS = "platforms"
CONF_ADDRESS = "address"
CONF_OWN_PASSWORD = "password"
CONF_FIRMWARE = "firmware"
CONF_SSDP_LOCATION = "ssdp_location"
CONF_SSDP_ST = "ssdp_st"
CONF_DEVICE_TYPE = "deviceType"
CONF_DEVICE_MODEL = "model"
CONF_MANUFACTURER = "manufacturer"
CONF_MANUFACTURER_URL = "manufacturerURL"
CONF_UDN = "UDN"
CONF_WORKER_COUNT = "command_worker_count"
CONF_FILE_PATH = "config_file_path"
CONF_GENERATE_EVENTS = "generate_events"
CONF_PARENT_ID = "parent_id"
CONF_WHO = "who"
CONF_WHERE = "where"
CONF_BUS_INTERFACE = "interface"
CONF_ZONE = "zone"
CONF_DIMMABLE = "dimmable"
CONF_GATEWAY = "gateway"
CONF_DEVICE_CLASS = "class"
CONF_INVERTED = "inverted"
CONF_ADVANCED_SHUTTER = "advanced"
CONF_HEATING_SUPPORT = "heat"
CONF_COOLING_SUPPORT = "cool"
CONF_FAN_SUPPORT = "fan"
CONF_STANDALONE = "standalone"
CONF_CENTRAL = "central"
CONF_SHORT_PRESS = "pushbutton_short_press"
CONF_SHORT_RELEASE = "pushbutton_short_release"
CONF_LONG_PRESS = "pushbutton_long_press"
CONF_LONG_RELEASE = "pushbutton_long_release"

# --- CEN / CEN+ scenario controls -------------------------------------------
# Stateless wall controls: they own no entity, they are registered as devices
# only so their buttons can be used as device triggers in the automation UI.
CEN_KIND = "cen"
CEN_PLUS_KIND = "cenplus"

SCENARIO_CONTROL_NAMES = {CEN_KIND: "CEN", CEN_PLUS_KIND: "CEN+"}
SCENARIO_CONTROL_MODELS = {
    CEN_KIND: "CEN scenario control",
    CEN_PLUS_KIND: "CEN+ scenario control",
}
# Bus event carrying the button presses of each kind.
SCENARIO_CONTROL_EVENTS = {
    CEN_KIND: "myhome_cen_event",
    CEN_PLUS_KIND: "myhome_cenplus_event",
}
# Buttons offered in the automation UI. The protocol allows 0-31, but physical
# wall plates never go past 8; higher buttons stay reachable via a YAML event
# trigger.
SCENARIO_CONTROL_BUTTONS = range(1, 9)


def scenario_control_id(mac: str, kind: str, object_id: int) -> str:
    """Device-registry identifier of a CEN/CEN+ control."""
    return f"{mac}-{kind}-{object_id}"
