"""A rolling history of past forecasts, kept on disk.

WeeWX archives what the station measured, never what was predicted, so there
is no record of what the forecast said yesterday unless something writes one.
This keeps that record: one entry per report, pruned to a retention window, so
the dashboard can show how the outlook has moved and whether it called the
weather that followed.

Deliberately append-and-prune rather than a database: a few hundred entries of
JSON costs nothing, needs no schema migration, and can be deleted at any time
without consequence.

No WeeWX imports, so it can be exercised standalone.
"""

import json
import logging
import os
import tempfile

log = logging.getLogger(__name__)

DEFAULT_RETENTION = 604800  # a week

# Entries closer together than this are collapsed, so a burst of report runs
# doesn't fill the history with near-duplicates.
MIN_INTERVAL = 240


class ForecastHistory:
    """Past forecasts, oldest first."""

    def __init__(self, path, retention=DEFAULT_RETENTION, min_interval=MIN_INTERVAL):
        self.path = path
        self.retention = retention
        self.min_interval = min_interval
        self.entries = []

    def load(self):
        """Read the history, starting fresh if it is missing or unreadable."""
        try:
            with open(self.path, "r") as fh:
                stored = json.load(fh)
        except FileNotFoundError:
            return self
        except (ValueError, OSError) as e:
            log.warning("weewxha: ignoring unreadable forecast history %s: %s", self.path, e)
            return self

        entries = stored.get("entries") if isinstance(stored, dict) else stored
        cleaned = []
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("timestamp") is not None:
                try:
                    entry["timestamp"] = int(entry["timestamp"])
                except (TypeError, ValueError):
                    continue
                cleaned.append(entry)
        self.entries = sorted(cleaned, key=lambda e: e["timestamp"])
        return self

    def add(self, timestamp, **fields):
        """Record a forecast, replacing anything at or near the same time."""
        timestamp = int(timestamp)
        entry = {"timestamp": timestamp}
        entry.update({k: v for k, v in fields.items() if v is not None})

        self.entries = [
            e for e in self.entries
            if abs(e["timestamp"] - timestamp) >= self.min_interval
        ]
        self.entries.append(entry)
        self.entries.sort(key=lambda e: e["timestamp"])
        self._prune(timestamp)
        return self

    def _prune(self, now):
        cutoff = now - self.retention
        # Entries from the future mean the clock moved; they would distort
        # every chart drawn afterwards.
        self.entries = [e for e in self.entries if cutoff <= e["timestamp"] <= now]

    def series(self, field):
        """(timestamp, value) pairs for one field, skipping entries without it."""
        points = []
        for entry in self.entries:
            value = entry.get(field)
            if value is None:
                continue
            points.append((entry["timestamp"], value))
        return points

    def recent(self, limit=12):
        """The most recent entries, newest first."""
        return list(reversed(self.entries[-limit:]))

    def changes(self, field="code", limit=8):
        """Points where `field` changed, newest first.

        A forecast that has read the same for two days is one event, not six
        hundred; this is what makes a readable "how it has moved" list.
        """
        transitions = []
        previous = None
        for entry in self.entries:
            value = entry.get(field)
            if value is None:
                continue
            if value != previous:
                transitions.append(entry)
                previous = value
        return list(reversed(transitions[-limit:]))

    def save(self):
        """Write atomically, so a crash mid-write can't corrupt the history."""
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".weewxha-hist-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump({"entries": self.entries}, fh)
                os.replace(tmp_path, self.path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            log.warning("weewxha: could not write forecast history %s: %s", self.path, e)
        return self
