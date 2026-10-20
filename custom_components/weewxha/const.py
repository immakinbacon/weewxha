"""Constants for the weewxha integration."""

DOMAIN = "weewxha"
DEFAULT_SCAN_INTERVAL = 300  # seconds; matches a typical WeeWX archive interval

# Home Assistant refuses a state longer than this, so anything wordier -- a
# forecast narrative, an alert headline -- lives in an attribute instead.
MAX_STATE_LENGTH = 255

# Whether to verify the feed's TLS certificate. A WeeWX server on an internal
# network is often behind a certificate from a private CA, which Home
# Assistant will not trust -- and unlike the browser there is no click-through.
CONF_VERIFY_SSL = "verify_ssl"

# Friendly labels for known WeeWX observation names. Anything not listed here
# falls back to the raw field name so new/uncommon observations still show up.
FIELD_LABELS: dict[str, str] = {
    "outTemp": "Outside Temperature",
    "inTemp": "Inside Temperature",
    "dewpoint": "Dew Point",
    "heatindex": "Heat Index",
    "windchill": "Wind Chill",
    "outHumidity": "Outside Humidity",
    "inHumidity": "Inside Humidity",
    "barometer": "Barometer",
    "windSpeed": "Wind Speed",
    "windGust": "Wind Gust",
    "windDir": "Wind Direction",
    "windGustDir": "Wind Gust Direction",
    "rainRate": "Rain Rate",
    "UV": "UV Index",
    "radiation": "Solar Radiation",
    "consBatteryVoltage": "Console Battery",
    "rxCheckPercent": "Signal Quality",
    "txBatteryStatus": "Battery",
    "outTemp_min": "Low Temperature Today",
    "outTemp_max": "High Temperature Today",
    "windSpeed_max": "Max Wind Speed Today",
    "rain_sum": "Rain Today",
    "zambretti": "Forecast",
    "zambretti_code": "Forecast Code",
    "pressure_trend": "Pressure Trend",
    "barometer_delta": "Pressure Change",
    "pressure": "Forecast Pressure",
    "condition": "Forecast Condition",
    "pressure_source": "Forecast Pressure Source",
}

# Icons for fields that carry no device class of their own, so they don't all
# land on Home Assistant's generic fallback icon.
FIELD_ICONS: dict[str, str] = {
    "zambretti": "mdi:weather-partly-cloudy",
    "zambretti_code": "mdi:alphabetical-variant",
    "pressure_trend": "mdi:gauge",
    "barometer_delta": "mdi:gauge",
    "pressure_source": "mdi:database-marker",
    "condition": "mdi:weather-partly-cloudy",
}
