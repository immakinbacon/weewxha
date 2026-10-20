"""Zambretti weather forecaster -- pure Python, no WeeWX imports.

The Zambretti forecaster turns three things a weather station already knows --
sea-level pressure, how that pressure is trending, and the time of year --
into one of 26 short forecast phrases. It is the algorithm behind the 1915
Negretti & Zambra "Pocket Weather Forecaster" slide rule, and it is
surprisingly good for a ~24 hour local outlook without any internet forecast
service.

Constants and lookup tables follow the published implementation lineage:
beteljuice.com's Java version -> honeysucklecottage.me.uk's Python port ->
pywws (pywws.forecast), with the algorithm itself documented at
http://www.meteormetrics.com/zambretti.htm

Kept free of WeeWX imports so it can be exercised standalone; the WeeWX
plumbing (database lookups, unit conversion) lives in weewxha_search.py.
"""

TREND_RISING = "rising"
TREND_STEADY = "steady"
TREND_FALLING = "falling"

# hPa/hour. The pressure is called steady inside this band; these are the
# thresholds the Zambretti tables were built around.
TREND_THRESHOLD = 0.1

TREND_ARROWS = {TREND_RISING: "↑", TREND_STEADY: "→", TREND_FALLING: "↓"}

ZAMBRETTI_TEXTS = {
    "A": "Settled fine",
    "B": "Fine weather",
    "C": "Becoming fine",
    "D": "Fine, becoming less settled",
    "E": "Fine, possible showers",
    "F": "Fairly fine, improving",
    "G": "Fairly fine, possible showers early",
    "H": "Fairly fine, showery later",
    "I": "Showery early, improving",
    "J": "Changeable, mending",
    "K": "Fairly fine, showers likely",
    "L": "Rather unsettled clearing later",
    "M": "Unsettled, probably improving",
    "N": "Showery, bright intervals",
    "O": "Showery, becoming less settled",
    "P": "Changeable, some rain",
    "Q": "Unsettled, short fine intervals",
    "R": "Unsettled, rain later",
    "S": "Unsettled, some rain",
    "T": "Mostly very unsettled",
    "U": "Occasional rain, worsening",
    "V": "Rain at times, very unsettled",
    "W": "Rain at frequent intervals",
    "X": "Rain, very unsettled",
    "Y": "Stormy, may improve",
    "Z": "Stormy, much rain",
}

# Pressure offset (hPa) per 16-point wind sector, starting at north and
# running clockwise: an onshore-vs-offshore style correction that nudges the
# forecast toward the weather that direction usually brings.
_WIND_OFFSETS = (
    5.2, 4.2, 3.2, 1.05, -1.1, -3.15, -5.2, -8.35,
    -11.5, -9.4, -7.3, -5.25, -3.2, -1.15, 0.9, 3.05,
)

# Forecast letters indexed by the computed dial position, one table per trend.
_RISING_LUT = "ABBCFGIJLMMQTY"
_FALLING_LUT = "BDHORUVXXZ"
_STEADY_LUT = "ABBBEKNNPPSWWXXXZ"

# Below this wind speed (m/s) the recorded direction is noise, so the wind
# correction is skipped rather than applied to an arbitrary heading.
CALM_WIND_MPS = 0.3

# Default local pressure range (hPa). Readings are normalised onto this scale,
# so a station in a persistently high- or low-pressure climate can narrow it
# and get the full range of forecasts instead of only the middle ones.
DEFAULT_BARO_LOWER = 950.0
DEFAULT_BARO_UPPER = 1050.0


def trend_state(rate):
    """Classify a pressure rate of change (hPa/hour) as rising/steady/falling.

    Returns None if the rate is unknown.
    """
    if rate is None:
        return None
    if rate >= TREND_THRESHOLD:
        return TREND_RISING
    if rate <= -TREND_THRESHOLD:
        return TREND_FALLING
    return TREND_STEADY


def zambretti_code(pressure, rate, month, wind_dir=None, wind_speed=None,
                   north=True, baro_lower=DEFAULT_BARO_LOWER,
                   baro_upper=DEFAULT_BARO_UPPER):
    """Return the Zambretti letter code 'A'-'Z' for the given conditions.

    Args:
        pressure (float): Sea-level (barometric) pressure, hPa.
        rate (float|None): Pressure rate of change, hPa/hour. None is treated
            as steady -- the forecast still stands, it just can't lean on a
            trend it doesn't have.
        month (int): Calendar month, 1-12, used to pick the seasonal offset.
        wind_dir (float|None): Wind direction in compass degrees.
        wind_speed (float|None): Wind speed, m/s. The direction correction is
            applied only when both are known and the wind is above calm.
        north (bool): True in the northern hemisphere.
        baro_lower (float): Bottom of the local pressure range, hPa.
        baro_upper (float): Top of the local pressure range, hPa.

    Returns:
        str: One of the 26 Zambretti letter codes.
    """
    span = baro_upper - baro_lower
    if not span:
        span = DEFAULT_BARO_UPPER - DEFAULT_BARO_LOWER
        baro_lower = DEFAULT_BARO_LOWER

    # Normalise onto the 950-1050 hPa scale the tables are calibrated for.
    pressure = 950.0 + (100.0 * (pressure - baro_lower) / span)

    if wind_dir is not None and wind_speed is not None and wind_speed >= CALM_WIND_MPS:
        sector = int(wind_dir / 22.5 + 0.5) % 16
        if not north:
            # Southern hemisphere: the same weather arrives from the opposite
            # side of the compass.
            sector = (sector + 8) % 16
        pressure += _WIND_OFFSETS[sector]

    # Southern-hemisphere summer is the northern-hemisphere winter months.
    summer = north == (4 <= month <= 9)

    state = trend_state(rate) or TREND_STEADY
    if state == TREND_RISING:
        if summer:
            pressure += 3.2
        dial = 0.1740 * (1031.40 - pressure)
        lut = _RISING_LUT
    elif state == TREND_FALLING:
        if summer:
            pressure -= 3.2
        dial = 0.1553 * (1029.95 - pressure)
        lut = _FALLING_LUT
    else:
        dial = 0.2314 * (1030.81 - pressure)
        lut = _STEADY_LUT

    return lut[min(max(int(dial + 0.5), 0), len(lut) - 1)]


def zambretti_text(code, texts=None):
    """Map a Zambretti letter code to its forecast phrase."""
    table = texts or ZAMBRETTI_TEXTS
    return table.get(code, ZAMBRETTI_TEXTS.get(code))
