"""Maps WeeWX unit tokens (as emitted in weewxha.json) to Home Assistant units.

WeeWX's three stock unit systems (US, Metric, MetricWX) use different tokens
for the same physical quantity, e.g. rain depth is reported as "inch", "cm",
or "mm" depending on how the station's [StdReport][[weewxha]] stanza is
configured. Each table below covers one physical quantity so field-specific
code in sensor.py never has to guess what a bare unit string means.
"""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfIrradiance,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfVolumetricFlux,
)

TEMPERATURE_UNITS = {
    "degree_F": UnitOfTemperature.FAHRENHEIT,
    "degree_C": UnitOfTemperature.CELSIUS,
    "degree_K": UnitOfTemperature.KELVIN,
}

PRESSURE_UNITS = {
    "inHg": UnitOfPressure.INHG,
    "mbar": UnitOfPressure.MBAR,
    "hPa": UnitOfPressure.HPA,
}

SPEED_UNITS = {
    "mile_per_hour": UnitOfSpeed.MILES_PER_HOUR,
    "km_per_hour": UnitOfSpeed.KILOMETERS_PER_HOUR,
    "meter_per_second": UnitOfSpeed.METERS_PER_SECOND,
    "knot": UnitOfSpeed.KNOTS,
}

DIRECTION_UNITS = {"degree_compass": DEGREE}

PERCENT_UNITS = {"percent": PERCENTAGE}

VOLT_UNITS = {"volt": UnitOfElectricPotential.VOLT}

IRRADIANCE_UNITS = {"watt_per_meter_squared": UnitOfIrradiance.WATTS_PER_SQUARE_METER}

# HA's UnitOfPrecipitationDepth/UnitOfVolumetricFlux only define inch- and
# mm-based members, but WeeWX's "Metric" (non-WX) preset reports rain in cm.
# Those tokens are mapped to the mm unit; WeewxHaSensor scales the value x10
# to compensate (see CM_SCALE_TOKENS below).
RAIN_DEPTH_UNITS = {
    "inch": UnitOfPrecipitationDepth.INCHES,
    "mm": UnitOfPrecipitationDepth.MILLIMETERS,
    "cm": UnitOfPrecipitationDepth.MILLIMETERS,
}

RAIN_RATE_UNITS = {
    "inch_per_hour": UnitOfVolumetricFlux.INCHES_PER_HOUR,
    "mm_per_hour": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
    "cm_per_hour": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
}

CM_SCALE_TOKENS = {"cm", "cm_per_hour"}

# section -> field -> (device_class, state_class, unit_table)
CURRENT_FIELD_SPECS: dict[str, tuple] = {
    "outTemp": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, TEMPERATURE_UNITS),
    "inTemp": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, TEMPERATURE_UNITS),
    "dewpoint": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, TEMPERATURE_UNITS),
    "heatindex": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, TEMPERATURE_UNITS),
    "windchill": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, TEMPERATURE_UNITS),
    "outHumidity": (SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, PERCENT_UNITS),
    "inHumidity": (SensorDeviceClass.HUMIDITY, SensorStateClass.MEASUREMENT, PERCENT_UNITS),
    "barometer": (SensorDeviceClass.ATMOSPHERIC_PRESSURE, SensorStateClass.MEASUREMENT, PRESSURE_UNITS),
    "windSpeed": (SensorDeviceClass.WIND_SPEED, SensorStateClass.MEASUREMENT, SPEED_UNITS),
    "windGust": (SensorDeviceClass.WIND_SPEED, SensorStateClass.MEASUREMENT, SPEED_UNITS),
    "windDir": (None, SensorStateClass.MEASUREMENT, DIRECTION_UNITS),
    "windGustDir": (None, SensorStateClass.MEASUREMENT, DIRECTION_UNITS),
    "rainRate": (SensorDeviceClass.PRECIPITATION_INTENSITY, SensorStateClass.MEASUREMENT, RAIN_RATE_UNITS),
    "UV": (None, SensorStateClass.MEASUREMENT, {}),
    "radiation": (SensorDeviceClass.IRRADIANCE, SensorStateClass.MEASUREMENT, IRRADIANCE_UNITS),
    "consBatteryVoltage": (SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, VOLT_UNITS),
    "rxCheckPercent": (None, SensorStateClass.MEASUREMENT, PERCENT_UNITS),
}

# The Zambretti forecast the skin computes from its own pressure history.
# "zambretti"/"zambretti_code"/"pressure_trend" are text states, so they carry
# no unit and no state class. "barometer_delta" is a signed change rather than
# a reading, so it is deliberately left without the pressure device class --
# that class implies an absolute measurement to Home Assistant.
FORECAST_FIELD_SPECS: dict[str, tuple] = {
    "zambretti": (None, None, {}),
    "zambretti_code": (None, None, {}),
    "pressure_trend": (SensorDeviceClass.ENUM, None, {}),
    # The broad sky condition the Zambretti code maps to, which is what the
    # dashboard draws its glyph from.
    "condition": (SensorDeviceClass.ENUM, None, {}),
    "pressure_source": (SensorDeviceClass.ENUM, None, {}),
    "barometer_delta": (None, SensorStateClass.MEASUREMENT, PRESSURE_UNITS),
    # The reading the forecast was actually computed from, which is the
    # station barometer unless the skin was pointed at a Home Assistant
    # sensor. Unlike barometer_delta this is an absolute pressure.
    "pressure": (
        SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        SensorStateClass.MEASUREMENT,
        PRESSURE_UNITS,
    ),
}

# Allowed states for SensorDeviceClass.ENUM fields; must match what the skin
# emits (see TREND_* in bin/user/weewxha_forecast.py and SOURCE_* in
# bin/user/weewxha_search.py).
FIELD_OPTIONS: dict[str, list[str]] = {
    "pressure_trend": ["rising", "steady", "falling"],
    "pressure_source": ["station", "homeassistant"],
    # Must match ZAMBRETTI_CONDITIONS in bin/user/weewxha_icons.py.
    "condition": ["sunny", "partly", "cloudy", "showers", "rain", "storm",
                  "snow", "fog", "windy"],
}

DAY_FIELD_SPECS: dict[str, tuple] = {
    "outTemp_min": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, TEMPERATURE_UNITS),
    "outTemp_max": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, TEMPERATURE_UNITS),
    "windSpeed_max": (SensorDeviceClass.WIND_SPEED, SensorStateClass.MEASUREMENT, SPEED_UNITS),
    "rain_sum": (SensorDeviceClass.PRECIPITATION, SensorStateClass.TOTAL_INCREASING, RAIN_DEPTH_UNITS),
}

# The skin's condition vocabulary mapped onto Home Assistant's own, which the
# weather card uses to pick its artwork. Ours is deliberately coarser: it
# describes a Zambretti phrase or an NWS icon, neither of which distinguishes
# rain from pouring rain.
HA_CONDITIONS = {
    "sunny": "sunny",
    "partly": "partlycloudy",
    "cloudy": "cloudy",
    "showers": "rainy",
    "rain": "rainy",
    "storm": "lightning-rainy",
    "snow": "snowy",
    "fog": "fog",
    "windy": "windy",
}

# Boolean/status fields surfaced as binary sensors instead of numeric sensors.
BINARY_FIELDS = {"txBatteryStatus"}
