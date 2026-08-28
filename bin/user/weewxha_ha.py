"""Read a pressure reading from a Home Assistant sensor, and keep enough of
its history on disk to derive a trend.

This is the one place where data flows *into* WeeWX rather than out of it. It
exists for stations with no barometer of their own: point it at a Home
Assistant pressure entity and the Zambretti forecast has something to work
with. WeeWX needs to be able to reach Home Assistant and needs a long-lived
access token.

The trend can't come from WeeWX's archive (the pressure was never in it), and
deliberately doesn't come from Home Assistant's history API either -- that
would tie the forecast to recorder retention and to whatever the recorder
happens to exclude. Instead each reading is appended to a small JSON file, so
the history is self-contained. The cost is a cold start: after a fresh setup
it takes a full trend window before the trend is known.

Standard library only, so installing the skin doesn't drag in dependencies.
"""

import json
import logging
import os
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


class HomeAssistantError(Exception):
    """Anything that stopped us getting a usable pressure reading."""


# Multiplier from a Home Assistant unit_of_measurement to hPa. Keys are
# lowercased; Home Assistant's pressure device class allows all of these.
PRESSURE_TO_HPA = {
    "pa": 0.01,
    "hpa": 1.0,
    "mbar": 1.0,
    "kpa": 10.0,
    "bar": 1000.0,
    "cbar": 10.0,
    "mmhg": 1.3332239,
    "inhg": 33.863886,
    "psi": 68.947573,
}

# States Home Assistant uses for "there is no reading right now".
_NO_READING = (None, "", "unknown", "unavailable", "none")

DEFAULT_TIMEOUT = 10.0
DEFAULT_RETENTION = 21600  # 6 hours: twice the default trend window


def normalize_url(url):
    """Accept 'homeassistant.local:8123' as readily as a full URL."""
    url = (url or "").strip().rstrip("/")
    if not url:
        raise HomeAssistantError("no Home Assistant URL configured")
    if "://" not in url:
        url = "http://" + url
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise HomeAssistantError("Home Assistant URL must be http or https: %s" % url)
    return url


def to_hpa(value, unit):
    """Convert a pressure reading in `unit` to hPa."""
    key = (unit or "").strip().lower()
    if key not in PRESSURE_TO_HPA:
        raise HomeAssistantError(
            "unrecognised pressure unit %r; set 'unit' in the skin's "
            "[[HomeAssistant]] section to one of: %s"
            % (unit, ", ".join(sorted(PRESSURE_TO_HPA)))
        )
    return value * PRESSURE_TO_HPA[key]


_warned_unverified = False


def build_ssl_context(verify=True, ca_file=None):
    """TLS settings for the request, or None to use Python's defaults.

    A Home Assistant behind a private CA -- common on an internal network --
    fails verification against the system trust store. Point `ca_file` at that
    CA and verification keeps working properly. Turning `verify` off is the
    last resort: it accepts any certificate, so anything on the network path
    can read the access token.
    """
    global _warned_unverified

    if not verify:
        if not _warned_unverified:
            log.warning(
                "weewxha: TLS certificate verification is disabled for Home "
                "Assistant; the access token is exposed to anything that can "
                "intercept the connection. Prefer ca_file."
            )
            _warned_unverified = True
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    if ca_file:
        try:
            return ssl.create_default_context(cafile=ca_file)
        except OSError as e:
            raise HomeAssistantError("could not read ca_file %s: %s" % (ca_file, e))

    return None


# Home Assistant's temperature units, to the tokens WeeWX uses.
TEMPERATURE_UNITS = {
    "\u00b0c": "degree_C",
    "c": "degree_C",
    "\u00b0f": "degree_F",
    "f": "degree_F",
    "k": "degree_K",
}


def fetch_state(url, token, entity_id, timeout=DEFAULT_TIMEOUT, verify=True, ca_file=None):
    """Return an entity's current numeric state and its unit.

    Raises HomeAssistantError with a message worth showing the user for every
    failure mode -- unreachable, bad token, wrong entity, non-numeric state.
    """
    if not token:
        raise HomeAssistantError("no Home Assistant access token configured")
    if not entity_id:
        raise HomeAssistantError(
            "no Home Assistant entity configured; set barometer_entity_id")

    context = build_ssl_context(verify, ca_file)

    endpoint = "%s/api/states/%s" % (normalize_url(url), urllib.parse.quote(entity_id))
    request = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": "Bearer %s" % token,
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise HomeAssistantError("Home Assistant rejected the access token (HTTP 401)")
        if e.code == 404:
            raise HomeAssistantError("Home Assistant has no entity %r (HTTP 404)" % entity_id)
        raise HomeAssistantError("HTTP %s from %s" % (e.code, endpoint))
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            raise HomeAssistantError(
                "TLS certificate for %s could not be verified (%s). If Home "
                "Assistant uses a private CA, set 'ca_file' to that CA "
                "certificate, or install it in the system trust store. Setting "
                "'verify = false' skips the check but exposes the token."
                % (endpoint, e.reason.verify_message or e.reason)
            )
        raise HomeAssistantError("could not reach %s: %s" % (endpoint, e.reason))
    except (ValueError, OSError) as e:
        raise HomeAssistantError("bad response from %s: %s" % (endpoint, e))

    state = payload.get("state")
    if isinstance(state, str):
        state = state.strip()
    if (state.lower() if isinstance(state, str) else state) in _NO_READING:
        raise HomeAssistantError("entity %s has no reading (state %r)" % (entity_id, state))

    try:
        value = float(state)
    except (TypeError, ValueError):
        raise HomeAssistantError("entity %s reported a non-numeric state %r" % (entity_id, state))

    unit = (payload.get("attributes") or {}).get("unit_of_measurement")
    return value, unit


def fetch_pressure(url, token, entity_id, timeout=DEFAULT_TIMEOUT, default_unit=None,
                   verify=True, ca_file=None):
    """An entity's pressure reading, in hPa."""
    value, unit = fetch_state(url, token, entity_id, timeout, verify, ca_file)
    return to_hpa(value, unit or default_unit)


def fetch_temperature(url, token, entity_id, timeout=DEFAULT_TIMEOUT, default_unit=None,
                      verify=True, ca_file=None):
    """An entity's temperature, as (value, WeeWX unit token)."""
    value, unit = fetch_state(url, token, entity_id, timeout, verify, ca_file)
    key = (unit or default_unit or "").strip().lower()
    token_name = TEMPERATURE_UNITS.get(key)
    if token_name is None:
        raise HomeAssistantError(
            "unrecognised temperature unit %r for %s; set 'inside_unit' to one "
            "of: C, F, K" % (unit, entity_id)
        )
    return value, token_name


def fetch_humidity(url, token, entity_id, timeout=DEFAULT_TIMEOUT, verify=True, ca_file=None):
    """An entity's relative humidity, as a percentage.

    Humidity is dimensionless, so an absent unit is normal rather than a
    problem; anything else is rejected in case the entity is not what was
    meant.
    """
    value, unit = fetch_state(url, token, entity_id, timeout, verify, ca_file)
    if unit and unit.strip() not in ("%", "percent"):
        raise HomeAssistantError(
            "entity %s reports %r, which is not a humidity" % (entity_id, unit))
    return value


class PressureHistory:
    """A short rolling history of pressure samples, persisted as JSON.

    Only as long as the forecast needs: samples older than `retention` are
    dropped on every write, so the file stays small and self-maintaining.
    """

    def __init__(self, path, entity_id, retention=DEFAULT_RETENTION):
        self.path = path
        self.entity_id = entity_id
        self.retention = retention
        self.samples = []

    def load(self):
        """Read the store, tolerating anything unreadable by starting fresh."""
        try:
            with open(self.path, "r") as fh:
                stored = json.load(fh)
        except FileNotFoundError:
            return self
        except (ValueError, OSError) as e:
            log.warning("weewxha: ignoring unreadable pressure history %s: %s", self.path, e)
            return self

        # History for a different entity says nothing about this one.
        if stored.get("entity_id") != self.entity_id:
            log.info("weewxha: pressure entity changed; starting a new history")
            return self

        samples = []
        for sample in stored.get("samples") or []:
            try:
                samples.append((int(sample[0]), float(sample[1])))
            except (TypeError, ValueError, IndexError):
                continue
        self.samples = sorted(samples)
        return self

    def add(self, timestamp, pressure):
        """Record a sample, replacing any already stored for that time."""
        timestamp = int(timestamp)
        self.samples = [s for s in self.samples if s[0] != timestamp]
        self.samples.append((timestamp, float(pressure)))
        self.samples.sort()
        self._prune(timestamp)
        return self

    def _prune(self, now):
        cutoff = now - self.retention
        # Samples from the future mean the clock moved; keeping them would
        # poison every later trend, so they go too.
        self.samples = [s for s in self.samples if cutoff <= s[0] <= now]

    def save(self):
        """Write atomically, so a crash mid-write can't corrupt the store."""
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".weewxha-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(
                        {"entity_id": self.entity_id, "samples": [list(s) for s in self.samples]},
                        fh,
                    )
                os.replace(tmp_path, self.path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            # A forecast without a trend beats no report at all.
            log.warning("weewxha: could not write pressure history %s: %s", self.path, e)
        return self

    def change(self, timestamp, pressure, period, tolerance):
        """Pressure change over `period` as (delta_hPa, elapsed_seconds).

        Uses the stored sample closest to `period` ago, provided it is within
        `tolerance` of that time -- so a gap in the history yields no trend
        rather than a trend measured over the wrong span. Returns None when
        there is no usable sample to compare against.
        """
        target = timestamp - period
        candidates = [s for s in self.samples if s[0] < timestamp]
        if not candidates:
            return None

        past = min(candidates, key=lambda s: abs(s[0] - target))
        if abs(past[0] - target) > tolerance:
            return None

        elapsed = timestamp - past[0]
        if elapsed <= 0:
            return None
        return pressure - past[1], elapsed
