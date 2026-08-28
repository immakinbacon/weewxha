"""Minimal time-series charts, rendered as inline SVG.

Drawn here rather than with a plotting library or a JavaScript chart for three
reasons: the page stays dependency-free and works offline, the markup carries
no colours of its own so the stylesheet can theme it for light and dark, and
values that never reach WeeWX's database -- the Home Assistant pressure, the
forecast history -- can be plotted just as easily as ones that do.

Colours come from CSS classes, never from attributes here, so a theme change
is a stylesheet change.

No WeeWX imports, so it can be exercised standalone.
"""

import math
import time

# A y-axis that always spans at least this much keeps a flat series from being
# drawn as dramatic noise across the full height of the chart.
#
# Keyed by the unit as displayed, because the same physical quantity needs a
# very different floor depending on it: 4 is a sensible minimum span in hPa
# and an absurd one in inHg, where it covers most of the range a barometer
# ever sees.
MIN_SPANS = {
    "inHg": 0.10,
    "mmHg": 2.5,
    "mbar": 3.0,
    "hPa": 3.0,
    "\u00b0F": 4.0,
    "\u00b0C": 2.0,
    "%": 5.0,
    "mph": 3.0,
    "km/h": 5.0,
    "m/s": 1.5,
    "knot": 3.0,
    "in": 0.10,
    "mm": 2.0,
    "cm": 0.2,
}
DEFAULT_MIN_SPAN = 1.0


def min_span_for(unit, values):
    """The smallest sensible y-axis span for a unit.

    Falls back to a small fraction of the readings themselves, so an unknown
    unit still gets a floor proportionate to the numbers involved rather than
    a fixed one that might be wildly wrong.
    """
    if unit in MIN_SPANS:
        return MIN_SPANS[unit]
    if values:
        magnitude = max(abs(v) for v in values)
        if magnitude:
            return max(magnitude * 0.01, 0.01)
    return DEFAULT_MIN_SPAN


def _escape(text):
    """Escape text for inclusion in SVG markup."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _nice_span(low, high, min_span):
    """Pad a value range so the line doesn't touch the frame."""
    if high < low:
        low, high = high, low
    span = high - low
    if span < min_span:
        centre = (high + low) / 2.0
        low, high = centre - min_span / 2.0, centre + min_span / 2.0
        span = high - low
    padding = span * 0.12
    return low - padding, high + padding


def _format_value(value, decimals):
    return ("%%.%df" % decimals) % value


class Series:
    """One line on a chart: points, a name, and the CSS class to draw it in."""

    def __init__(self, points, name="", css_class="chart-line", decimals=1):
        # Discard anything unusable, then order by time.
        cleaned = []
        for point in points or []:
            try:
                timestamp, value = point[0], point[1]
            except (TypeError, IndexError):
                continue
            if timestamp is None or value is None:
                continue
            try:
                cleaned.append((int(timestamp), float(value)))
            except (TypeError, ValueError):
                continue
        self.points = sorted(cleaned)
        self.name = name
        self.css_class = css_class
        self.decimals = decimals

    def __len__(self):
        return len(self.points)

    @property
    def latest(self):
        return self.points[-1][1] if self.points else None

    @property
    def minimum(self):
        return min(value for _, value in self.points) if self.points else None

    @property
    def maximum(self):
        return max(value for _, value in self.points) if self.points else None


def _nice_step(span, target_ticks):
    """A round number close to span/target_ticks: 1, 2, 2.5 or 5 times a power of ten."""
    if span <= 0 or target_ticks <= 0:
        return 1.0
    rough = span / float(target_ticks)
    magnitude = 10.0 ** math.floor(math.log10(rough))
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        if rough <= multiple * magnitude:
            return multiple * magnitude
    return 10.0 * magnitude


def _value_ticks(low, high, target=4):
    """Round values to label the y-axis with, inside [low, high]."""
    step = _nice_step(high - low, target)
    first = math.ceil(low / step) * step
    ticks = []
    value = first
    while value <= high + step * 0.001 and len(ticks) < 12:
        ticks.append(round(value, 10))
        value += step
    return ticks


# Time gridline spacing: (span up to, interval, label format). A day of data
# gets a mark every three hours; a week gets one a day.
_TIME_STEPS = (
    (2 * 3600, 900, "%H:%M"),
    (6 * 3600, 3600, "%H:%M"),
    (14 * 3600, 2 * 3600, "%H:%M"),
    (2 * 86400, 3 * 3600, "%H:%M"),
    (4 * 86400, 12 * 3600, "%a %H:%M"),
    (10 * 86400, 86400, "%a"),
)


def _time_ticks(t_min, t_max):
    """Timestamps to mark on the x-axis, aligned to round clock times."""
    span = t_max - t_min
    interval, fmt = _TIME_STEPS[-1][1], _TIME_STEPS[-1][2]
    for limit, step, label_format in _TIME_STEPS:
        if span <= limit:
            interval, fmt = step, label_format
            break

    # Align to the local clock, so marks land on the hour rather than on
    # whenever the first sample happened to be taken.
    offset = -time.timezone
    first = math.ceil((t_min + offset) / float(interval)) * interval - offset
    ticks = []
    stamp = first
    while stamp <= t_max and len(ticks) < 24:
        ticks.append(int(stamp))
        stamp += interval
    return ticks, fmt


def line_chart(series, width=520, height=200, unit="", min_span=None, value_ticks=4):
    """Render one or more Series as an SVG line chart.

    Returns None when there is nothing worth drawing -- a chart of a single
    point is a dot with no information in it, and the caller can decide
    whether to show a placeholder instead.
    """
    if isinstance(series, Series):
        series = [series]
    series = [s for s in series if len(s) >= 2]
    if not series:
        return None

    left, right, top, bottom = 46, 12, 14, 32
    plot_width = width - left - right
    plot_height = height - top - bottom

    all_points = [p for s in series for p in s.points]
    t_min = min(t for t, _ in all_points)
    t_max = max(t for t, _ in all_points)
    if t_max == t_min:
        return None

    values = [v for _, v in all_points]
    v_low, v_high = _nice_span(
        min(values),
        max(values),
        min_span if min_span is not None else min_span_for(unit, values),
    )
    v_span = v_high - v_low or 1.0
    decimals = series[0].decimals

    def x_of(timestamp):
        return left + (timestamp - t_min) / float(t_max - t_min) * plot_width

    def y_of(value):
        return top + (v_high - value) / v_span * plot_height

    # Default aspect handling, so the drawing is never stretched out of shape.
    parts = [
        '<svg class="chart" viewBox="0 0 %d %d" role="img" aria-label="%s">'
        % (width, height, _escape(_describe(series, unit)))
    ]

    # Horizontal gridlines at round values.
    for value in _value_ticks(v_low, v_high, value_ticks):
        y = y_of(value)
        parts.append(
            '<line class="chart-grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>'
            % (left, y, width - right, y)
        )
        parts.append(
            '<text class="chart-axis" x="%d" y="%.1f" text-anchor="end">%s</text>'
            % (left - 6, y + 3.5, _escape(_format_value(value, decimals)))
        )

    # Vertical gridlines on round clock times, so the gap between readings
    # can actually be located in time.
    ticks, time_format = _time_ticks(t_min, t_max)
    # Every mark gets a gridline, but labelling all of them crowds a narrow
    # chart into unreadability, so label every nth.
    label_every = max(1, int(math.ceil(len(ticks) / 5.0)))
    for index, stamp in enumerate(ticks):
        x = x_of(stamp)
        parts.append(
            '<line class="chart-grid chart-grid-time" x1="%.1f" y1="%d" x2="%.1f" y2="%d"/>'
            % (x, top, x, top + plot_height)
        )
        if index % label_every:
            continue
        parts.append(
            '<text class="chart-axis" x="%.1f" y="%d" text-anchor="middle">%s</text>'
            % (x, height - 10, _escape(time.strftime(time_format, time.localtime(stamp))))
        )

    # Axis frame: a baseline and a left edge to sit the data against.
    parts.append(
        '<line class="chart-frame" x1="%d" y1="%d" x2="%d" y2="%d"/>'
        % (left, top + plot_height, width - right, top + plot_height)
    )
    parts.append(
        '<line class="chart-frame" x1="%d" y1="%d" x2="%d" y2="%d"/>'
        % (left, top, left, top + plot_height)
    )

    for line in series:
        coordinates = " ".join(
            "%.1f,%.1f" % (x_of(t), y_of(v)) for t, v in line.points
        )
        parts.append(
            '<polyline class="%s" points="%s" fill="none"/>'
            % (_escape(line.css_class), coordinates)
        )
        # A dot on the most recent reading, so "now" is unambiguous.
        last_t, last_v = line.points[-1]
        parts.append(
            '<circle class="%s-dot" cx="%.1f" cy="%.1f" r="2.5"/>'
            % (_escape(line.css_class), x_of(last_t), y_of(last_v))
        )

    parts.append("</svg>")
    return "".join(parts)


def _describe(series, unit):
    """Accessible summary, since the chart itself conveys nothing to a reader."""
    bits = []
    for line in series:
        bits.append(
            "%s from %s to %s %s"
            % (
                line.name or "series",
                _format_value(line.minimum, line.decimals),
                _format_value(line.maximum, line.decimals),
                unit,
            )
        )
    return "; ".join(bits).strip()
