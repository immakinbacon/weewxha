"""Weather glyphs for the local forecast, as inline SVG.

The National Weather Service supplies an icon URL with each of its forecast
periods, but Zambretti produces only a letter code, so its icon has to be
derived from the phrase that code stands for.

The glyphs are Bootstrap Icons, embedded rather than hand-drawn so they carry
a designer's consistency of weight and optical sizing, and inline rather than
linked so the dashboard keeps working with no network. Every path uses
currentColor, so they follow the stylesheet into light or dark theme.

    Bootstrap Icons -- https://icons.getbootstrap.com
    The MIT License (MIT)
    Copyright (c) 2019-2024 The Bootstrap Authors

No WeeWX imports, so it can be exercised standalone.
"""

# Zambretti letter code -> broad condition. The 26 phrases collapse into six
# recognisable pictures; see ZAMBRETTI_TEXTS in weewxha_forecast.py for the
# wording each letter stands for.
ZAMBRETTI_CONDITIONS = {
    "A": "sunny",      # Settled fine
    "B": "sunny",      # Fine weather
    "C": "sunny",      # Becoming fine
    "D": "partly",     # Fine, becoming less settled
    "E": "partly",     # Fine, possible showers
    "F": "partly",     # Fairly fine, improving
    "G": "partly",     # Fairly fine, possible showers early
    "H": "showers",    # Fairly fine, showery later
    "I": "showers",    # Showery early, improving
    "J": "partly",     # Changeable, mending
    "K": "showers",    # Fairly fine, showers likely
    "L": "cloudy",     # Rather unsettled clearing later
    "M": "cloudy",     # Unsettled, probably improving
    "N": "showers",    # Showery, bright intervals
    "O": "showers",    # Showery, becoming less settled
    "P": "rain",       # Changeable, some rain
    "Q": "cloudy",     # Unsettled, short fine intervals
    "R": "rain",       # Unsettled, rain later
    "S": "rain",       # Unsettled, some rain
    "T": "cloudy",     # Mostly very unsettled
    "U": "rain",       # Occasional rain, worsening
    "V": "rain",       # Rain at times, very unsettled
    "W": "rain",       # Rain at frequent intervals
    "X": "rain",       # Rain, very unsettled
    "Y": "storm",      # Stormy, may improve
    "Z": "storm",      # Stormy, much rain
}

CONDITION_LABELS = {
    "sunny": "Clear",
    "partly": "Partly cloudy",
    "cloudy": "Cloudy",
    "showers": "Showers",
    "rain": "Rain",
    "storm": "Storm",
    "snow": "Snow",
    "fog": "Fog",
    "windy": "Windy",
}

# The National Weather Service encodes the condition in its icon URL, e.g.
# .../icons/land/day/tsra_hi,40?size=medium. Mapping those tokens onto the
# same glyph set as Zambretti keeps the page visually consistent, avoids
# fetching remote raster images that ignore the theme, and means the dashboard
# still draws when offline. Longest tokens first, so "rain_showers" is not
# matched by "rain".
_NWS_ICON_TOKENS = (
    ("tsra", "storm"),
    ("rain_showers", "showers"),
    ("rain_snow", "snow"),
    ("rain_sleet", "snow"),
    ("snow_sleet", "snow"),
    ("snow_fzra", "snow"),
    ("fzra", "snow"),
    ("sleet", "snow"),
    ("blizzard", "snow"),
    ("snow", "snow"),
    ("rain", "rain"),
    ("fog", "fog"),
    ("haze", "fog"),
    ("smoke", "fog"),
    ("dust", "fog"),
    ("wind", "windy"),
    ("ovc", "cloudy"),
    ("bkn", "cloudy"),
    ("sct", "partly"),
    ("few", "partly"),
    ("skc", "sunny"),
    ("hot", "sunny"),
    ("cold", "snow"),
)

ICON_VIEWBOX = "0 0 16 16"

# Path data lifted verbatim from Bootstrap Icons (see the module docstring).
# Keyed by condition; the icon each came from is named alongside.
_ICON_PATHS = {
    # sun
    "sunny": (
        "M8 11a3 3 0 1 1 0-6 3 3 0 0 1 0 6m0 1a4 4 0 1 0 0-8 4 4 0 0 0 0 8M8 0a.5.5 0 0 1 "
        ".5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 0 1 8 0m0 13a.5.5 0 0 1 .5.5v2a.5.5 0 0 1-1 0v-2A.5.5 0 "
        "0 1 8 13m8-5a.5.5 0 0 1-.5.5h-2a.5.5 0 0 1 0-1h2a.5.5 0 0 1 .5.5M3 8a.5.5 0 0 "
        "1-.5.5h-2a.5.5 0 0 1 0-1h2A.5.5 0 0 1 3 8m10.657-5.657a.5.5 0 0 1 0 .707l-1.414 "
        "1.415a.5.5 0 1 1-.707-.708l1.414-1.414a.5.5 0 0 1 .707 0m-9.193 9.193a.5.5 0 0 1 0 "
        ".707L3.05 13.657a.5.5 0 0 1-.707-.707l1.414-1.414a.5.5 0 0 1 .707 0m9.193 2.121a.5.5 0 0"
        " 1-.707 0l-1.414-1.414a.5.5 0 0 1 .707-.707l1.414 1.414a.5.5 0 0 1 0 .707M4.464 "
        "4.465a.5.5 0 0 1-.707 0L2.343 3.05a.5.5 0 1 1 .707-.707l1.414 1.414a.5.5 0 0 1 0 .708"
        ,
    ),
    # cloud-sun
    "partly": (
        "M7 8a3.5 3.5 0 0 1 3.5 3.555.5.5 0 0 0 .624.492A1.503 1.503 0 0 1 13 13.5a1.5 1.5 0 0 "
        "1-1.5 1.5H3a2 2 0 1 1 .1-3.998.5.5 0 0 0 .51-.375A3.5 3.5 0 0 1 7 8m4.473 3a4.5 4.5 0 0 "
        "0-8.72-.99A3 3 0 0 0 3 16h8.5a2.5 2.5 0 0 0 0-5z"
        ,
        "M10.5 1.5a.5.5 0 0 0-1 0v1a.5.5 0 0 0 1 0zm3.743 1.964a.5.5 0 1 "
        "0-.707-.707l-.708.707a.5.5 0 0 0 .708.708zm-7.779-.707a.5.5 0 0 0-.707.707l.707.708a.5.5"
        " 0 1 0 .708-.708zm1.734 3.374a2 2 0 1 1 3.296 2.198q.3.423.516.898a3 3 0 1 "
        "0-4.84-3.225q.529.017 1.028.129m4.484 4.074c.6.215 1.125.59 1.522 1.072a.5.5 0 0 0 "
        ".039-.742l-.707-.707a.5.5 0 0 0-.854.377M14.5 6.5a.5.5 0 0 0 0 1h1a.5.5 0 0 0 0-1z"
        ,
    ),
    # cloud
    "cloudy": (
        "M4.406 3.342A5.53 5.53 0 0 1 8 2c2.69 0 4.923 2 5.166 4.579C14.758 6.804 16 8.137 16 "
        "9.773 16 11.569 14.502 13 12.687 13H3.781C1.708 13 0 11.366 0 9.318c0-1.763 1.266-3.223 "
        "2.942-3.593.143-.863.698-1.723 1.464-2.383m.653.757c-.757.653-1.153 1.44-1.153 "
        "2.056v.448l-.445.049C2.064 6.805 1 7.952 1 9.318 1 10.785 2.23 12 3.781 12h8.906C13.98 "
        "12 15 10.988 15 9.773c0-1.216-1.02-2.228-2.313-2.228h-.5v-.5C12.188 4.825 10.328 3 8 "
        "3a4.53 4.53 0 0 0-2.941 1.1z"
        ,
    ),
    # cloud-drizzle
    "showers": (
        "M4.158 12.025a.5.5 0 0 1 .316.633l-.5 1.5a.5.5 0 0 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.317m6 0a.5.5 0 0 1 .316.633l-.5 1.5a.5.5 0 0 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.317m-3.5 1.5a.5.5 0 0 1 .316.633l-.5 1.5a.5.5 0 0 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.317m6 0a.5.5 0 0 1 .316.633l-.5 1.5a.5.5 0 1 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.317m.747-8.498a5.001 5.001 0 0 0-9.499-1.004A3.5 3.5 0 1 0 3.5 11H13a3 3 0 0 0 "
        ".405-5.973M8.5 2a4 4 0 0 1 3.976 3.555.5.5 0 0 0 .5.445H13a2 2 0 0 1 0 4H3.5a2.5 2.5 0 1"
        " 1 .605-4.926.5.5 0 0 0 .596-.329A4 4 0 0 1 8.5 2"
        ,
    ),
    # cloud-rain-heavy
    "rain": (
        "M4.176 11.032a.5.5 0 0 1 .292.643l-1.5 4a.5.5 0 1 1-.936-.35l1.5-4a.5.5 0 0 1 "
        ".644-.293m3 0a.5.5 0 0 1 .292.643l-1.5 4a.5.5 0 1 1-.936-.35l1.5-4a.5.5 0 0 1 "
        ".644-.293m3 0a.5.5 0 0 1 .292.643l-1.5 4a.5.5 0 1 1-.936-.35l1.5-4a.5.5 0 0 1 "
        ".644-.293m3 0a.5.5 0 0 1 .292.643l-1.5 4a.5.5 0 0 1-.936-.35l1.5-4a.5.5 0 0 1 "
        ".644-.293m.229-7.005a5.001 5.001 0 0 0-9.499-1.004A3.5 3.5 0 1 0 3.5 10H13a3 3 0 0 0 "
        ".405-5.973M8.5 1a4 4 0 0 1 3.976 3.555.5.5 0 0 0 .5.445H13a2 2 0 0 1 0 4H3.5a2.5 2.5 0 1"
        " 1 .605-4.926.5.5 0 0 0 .596-.329A4 4 0 0 1 8.5 1"
        ,
    ),
    # cloud-lightning-rain
    "storm": (
        "M2.658 11.026a.5.5 0 0 1 .316.632l-.5 1.5a.5.5 0 1 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.316m9.5 0a.5.5 0 0 1 .316.632l-.5 1.5a.5.5 0 1 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.316m-7.5 1.5a.5.5 0 0 1 .316.632l-.5 1.5a.5.5 0 1 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.316m9.5 0a.5.5 0 0 1 .316.632l-.5 1.5a.5.5 0 1 1-.948-.316l.5-1.5a.5.5 0 0 1 "
        ".632-.316m-.753-8.499a5.001 5.001 0 0 0-9.499-1.004A3.5 3.5 0 1 0 3.5 10H13a3 3 0 0 0 "
        ".405-5.973M8.5 1a4 4 0 0 1 3.976 3.555.5.5 0 0 0 .5.445H13a2 2 0 0 1 0 4H3.5a2.5 2.5 0 1"
        " 1 .605-4.926.5.5 0 0 0 .596-.329A4 4 0 0 1 8.5 1M7.053 11.276A.5.5 0 0 1 7.5 11h1a.5.5 "
        "0 0 1 .474.658l-.28.842H9.5a.5.5 0 0 1 .39.812l-2 2.5a.5.5 0 0 1-.875-.433L7.36 "
        "14H6.5a.5.5 0 0 1-.447-.724z"
        ,
    ),
    # cloud-snow
    "snow": (
        "M13.405 4.277a5.001 5.001 0 0 0-9.499-1.004A3.5 3.5 0 1 0 3.5 10.25H13a3 3 0 0 0 "
        ".405-5.973M8.5 1.25a4 4 0 0 1 3.976 3.555.5.5 0 0 0 .5.445H13a2 2 0 0 1-.001 4H3.5a2.5 "
        "2.5 0 1 1 .605-4.926.5.5 0 0 0 .596-.329A4 4 0 0 1 8.5 1.25M2.625 11.5a.25.25 0 0 1 "
        ".25.25v.57l.501-.287a.25.25 0 0 1 .248.434l-.495.283.495.283a.25.25 0 0 "
        "1-.248.434l-.501-.286v.569a.25.25 0 1 1-.5 0v-.57l-.501.287a.25.25 0 0 "
        "1-.248-.434l.495-.283-.495-.283a.25.25 0 0 1 .248-.434l.501.286v-.569a.25.25 0 0 1 "
        ".25-.25m2.75 2a.25.25 0 0 1 .25.25v.57l.501-.287a.25.25 0 0 1 "
        ".248.434l-.495.283.495.283a.25.25 0 0 1-.248.434l-.501-.286v.569a.25.25 0 1 1-.5 "
        "0v-.57l-.501.287a.25.25 0 0 1-.248-.434l.495-.283-.495-.283a.25.25 0 0 1 "
        ".248-.434l.501.286v-.569a.25.25 0 0 1 .25-.25m5.5 0a.25.25 0 0 1 "
        ".25.25v.57l.501-.287a.25.25 0 0 1 .248.434l-.495.283.495.283a.25.25 0 0 "
        "1-.248.434l-.501-.286v.569a.25.25 0 1 1-.5 0v-.57l-.501.287a.25.25 0 0 "
        "1-.248-.434l.495-.283-.495-.283a.25.25 0 0 1 .248-.434l.501.286v-.569a.25.25 0 0 1 "
        ".25-.25m-2.75-2a.25.25 0 0 1 .25.25v.57l.501-.287a.25.25 0 0 1 "
        ".248.434l-.495.283.495.283a.25.25 0 0 1-.248.434l-.501-.286v.569a.25.25 0 1 1-.5 "
        "0v-.57l-.501.287a.25.25 0 0 1-.248-.434l.495-.283-.495-.283a.25.25 0 0 1 "
        ".248-.434l.501.286v-.569a.25.25 0 0 1 .25-.25m5.5 0a.25.25 0 0 1 "
        ".25.25v.57l.501-.287a.25.25 0 0 1 .248.434l-.495.283.495.283a.25.25 0 0 "
        "1-.248.434l-.501-.286v.569a.25.25 0 1 1-.5 0v-.57l-.501.287a.25.25 0 0 "
        "1-.248-.434l.495-.283-.495-.283a.25.25 0 0 1 .248-.434l.501.286v-.569a.25.25 0 0 1 "
        ".25-.25"
        ,
    ),
    # cloud-fog
    "fog": (
        "M3 13.5a.5.5 0 0 1 .5-.5h9a.5.5 0 0 1 0 1h-9a.5.5 0 0 1-.5-.5m0 2a.5.5 0 0 1 "
        ".5-.5h9a.5.5 0 0 1 0 1h-9a.5.5 0 0 1-.5-.5m10.405-9.473a5.001 5.001 0 0 "
        "0-9.499-1.004A3.5 3.5 0 1 0 3.5 12H13a3 3 0 0 0 .405-5.973M8.5 3a4 4 0 0 1 3.976 "
        "3.555.5.5 0 0 0 .5.445H13a2 2 0 0 1 0 4H3.5a2.5 2.5 0 1 1 .605-4.926.5.5 0 0 0 "
        ".596-.329A4 4 0 0 1 8.5 3"
        ,
    ),
    # wind
    "windy": (
        "M12.5 2A2.5 2.5 0 0 0 10 4.5a.5.5 0 0 1-1 0A3.5 3.5 0 1 1 12.5 8H.5a.5.5 0 0 1 "
        "0-1h12a2.5 2.5 0 0 0 0-5m-7 1a1 1 0 0 0-1 1 .5.5 0 0 1-1 0 2 2 0 1 1 2 2h-5a.5.5 0 0 1 "
        "0-1h5a1 1 0 0 0 0-2M0 9.5A.5.5 0 0 1 .5 9h10.042a3 3 0 1 1-3 3 .5.5 0 0 1 1 0 2 2 0 1 0 "
        "2-2H.5a.5.5 0 0 1-.5-.5"
        ,
    ),
}


# Moon phase names, by how much of the disc is lit and which way it is going.
MOON_PHASES = (
    (2, "New moon", "New moon"),
    (48, "Waxing crescent", "Waning crescent"),
    (52, "First quarter", "Last quarter"),
    (98, "Waxing gibbous", "Waning gibbous"),
    (101, "Full moon", "Full moon"),
)


def moon_phase_name(fullness, waxing=True):
    """A short name for a phase, e.g. "Waxing gibbous"."""
    if fullness is None:
        return None
    for limit, waxing_name, waning_name in MOON_PHASES:
        if fullness < limit:
            return waxing_name if waxing else waning_name
    return "Full moon"


def moon_svg(fullness, waxing=True, size=40):
    """Draw the moon at a given illumination, rather than picking a stock image.

    The lit region is bounded by the disc on one side and by the terminator on
    the other. The terminator is an ellipse seen edge-on, so its width tracks
    the illumination directly: half-lit is a straight line, and it bulges away
    from the lit side for a crescent and toward it for a gibbous moon. Drawing
    it means every percentage renders truthfully instead of snapping to one of
    eight pictures.
    """
    if fullness is None:
        return None
    fullness = max(0.0, min(100.0, float(fullness)))

    radius, centre = 16.0, 20.0
    top, bottom = centre - radius, centre + radius
    # +1 at new, 0 at half, -1 at full.
    k = 1.0 - 2.0 * (fullness / 100.0)
    terminator_rx = abs(k) * radius

    # The outer edge runs down the lit side; the terminator returns up the
    # middle. Which way each arc sweeps decides crescent versus gibbous.
    outer_sweep = 1 if waxing else 0
    inner_sweep = (0 if k > 0 else 1) if waxing else (1 if k > 0 else 0)

    lit = (
        'M %.1f,%.1f A %.1f,%.1f 0 0,%d %.1f,%.1f A %.1f,%.1f 0 0,%d %.1f,%.1f Z'
        % (centre, top, radius, radius, outer_sweep, centre, bottom,
           terminator_rx, radius, inner_sweep, centre, top)
    )

    return (
        '<svg class="wx-icon wx-moon" viewBox="0 0 40 40" width="%d" height="%d" '
        'role="img" aria-label="%s, %d%% lit">'
        '<circle class="moon-dark" cx="%.1f" cy="%.1f" r="%.1f"/>'
        '<path class="moon-lit" d="%s"/>'
        "</svg>"
        % (size, size, _escape(moon_phase_name(fullness, waxing) or "Moon"),
           round(fullness), centre, centre, radius, lit)
    )


def _escape(text):
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;")
        .replace(">", "&gt;").replace('"', "&quot;")
    )


def condition_for_code(code):
    """The broad condition a Zambretti letter code represents."""
    if not code:
        return None
    return ZAMBRETTI_CONDITIONS.get(str(code).strip().upper()[:1])


def condition_for_nws_icon(url):
    """The condition an NWS icon URL describes, or None.

    The URL may name two periods ("...day/rain/tsra_hi"); the first wins,
    since it describes the earlier and usually more relevant half.
    """
    if not url:
        return None
    path = str(url).split("?", 1)[0]
    # Drop the fixed prefix, leaving just the condition segments.
    segments = [s for s in path.split("/") if s][-2:]
    for segment in segments:
        name = segment.split(",", 1)[0].lower()
        for token, condition in _NWS_ICON_TOKENS:
            if token in name:
                return condition
    return None


def condition_label(condition):
    return CONDITION_LABELS.get(condition, "")


def icon_svg(condition, size=44, extra_class=""):
    """An inline SVG glyph for a condition, or None if there isn't one.

    Carries no colour of its own -- fill is currentColor -- so the stylesheet
    paints it and it follows the theme.
    """
    paths = _ICON_PATHS.get(condition)
    if not paths:
        return None
    body = "".join('<path d="%s"/>' % d for d in paths)
    classes = "wx-icon wx-icon-%s%s" % (condition, (" " + extra_class) if extra_class else "")
    return (
        '<svg class="%s" viewBox="%s" width="%d" height="%d" fill="currentColor" '
        'role="img" aria-label="%s">%s</svg>'
        % (classes, ICON_VIEWBOX, size, size, condition_label(condition) or condition, body)
    )


# A favicon cannot inherit page CSS, so it needs a colour of its own. This one
# reads against both a light and a dark browser tab.
FAVICON_COLOUR = "#3b8fd6"


def favicon_data_uri(condition, colour=FAVICON_COLOUR):
    """The condition glyph as a data: URI, for use as a favicon.

    Inline rather than a file, so the tab icon follows the forecast without
    the skin having to write and clean up a dozen images.
    """
    paths = _ICON_PATHS.get(condition) or _ICON_PATHS.get("partly")
    body = "".join('<path d="%s"/>' % d for d in paths)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="%s">%s</svg>'
        % (colour, body)
    )
    # Percent-encode the few characters that cannot appear raw in a URI.
    encoded = (
        svg.replace("%", "%25").replace("#", "%23").replace("<", "%3C")
        .replace(">", "%3E").replace('"', "'").replace("\n", "")
    )
    return "data:image/svg+xml," + encoded


def icon_for_code(code, size=44, extra_class=""):
    """Convenience: Zambretti letter code straight to an SVG glyph."""
    return icon_svg(condition_for_code(code), size, extra_class)
