from homeassistant.const import Platform

DOMAIN = "asterisk_pbx"
DEFAULT_HOST = "homeassistant.local"
DEFAULT_PORT = 8099
DEFAULT_SCAN_INTERVAL = 15
CONF_SCAN_INTERVAL = "scan_interval"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
