"""Red Regional integration constants."""

from typing import Final

DOMAIN: Final = "red_regional"

API_BASE: Final = "https://phone.dtpr.transapp.cl/v7/phone"
APP_VERSION: Final = "2.5.1"
OS_TYPE: Final = "Android"

ATTRIBUTION: Final = "Datos: DTPR Red Regional (no oficial)"

DEFAULT_TIME_ZONE: Final = "America/Santiago"
REQUEST_TIMEOUT_S: Final = 10

DEFAULT_SCAN_INTERVAL_S: Final = 60
MIN_SCAN_INTERVAL_S: Final = 30
MAX_SCAN_INTERVAL_S: Final = 600

DEFAULT_MAX_DEPARTURES: Final = 5
MIN_MAX_DEPARTURES: Final = 1
MAX_MAX_DEPARTURES: Final = 15

DEFAULT_LOOK_AHEAD_MIN: Final = 120
MIN_LOOK_AHEAD_MIN: Final = 15
MAX_LOOK_AHEAD_MIN: Final = 360

DEFAULT_WALK_OFFSET_MIN: Final = 0
MIN_WALK_OFFSET_MIN: Final = 0
MAX_WALK_OFFSET_MIN: Final = 30

CONF_ZONE_UUID: Final = "zone_uuid"
CONF_ZONE_NAME: Final = "zone_name"
CONF_STOP_CODE: Final = "stop_code"
CONF_ROUTES_WHITELIST: Final = "routes_whitelist"
CONF_DESTINATIONS: Final = "destinations"
CONF_MAX_DEPARTURES: Final = "max_departures"
CONF_LOOK_AHEAD_MIN: Final = "look_ahead_min"
CONF_WALK_OFFSET_MIN: Final = "walk_offset_min"
CONF_TRACK_VEHICLES: Final = "track_vehicles"
CONF_TRACKED_ROUTES: Final = "tracked_routes"
CONF_SCAN_INTERVAL_S: Final = "scan_interval_s"
CONF_PHONE_ID: Final = "phone_id"
CONF_NAME_OVERRIDE: Final = "name_override"

STORAGE_DIR: Final = "red_regional"

FALLBACK_ZONES: Final = {
    "f083f24e-7fee-4fdc-9520-dbbdae877f07": "Gran Concepción",
    "50cde66c-2b67-4702-afa8-1f190249d9b8": "Talca",
    "c28e2682-b083-41ba-8827-5caac8b86181": "Temuco",
}
