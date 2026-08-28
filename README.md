# weewxha

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-support-FFDD00?style=flat-square&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/immakinbacon)

Brings [WeeWX](https://www.weewx.com/) weather station data into
[Home Assistant](https://www.home-assistant.io/) — no add-on container
required. It has two halves:

1. **`skins/weewxha`** — a WeeWX skin. It renders a small, appealing
   dashboard (`index.html`) alongside a machine-readable `weewxha.json` data
   feed, using WeeWX's own archive/unit-conversion logic. Works with WeeWX
   4.x and 5.x.
2. **`custom_components/weewxha`** — a Home Assistant custom integration
   (HACS-compatible). You give it the URL where `weewxha.json` is published;
   it polls that URL on a `DataUpdateCoordinator` and creates sensor /
   binary_sensor entities for whatever observations your station reports.

Architecture: WeeWX already runs its own report generator on your station
hardware (or wherever WeeWX lives) and needs no new networking beyond
whatever already serves its `public_html` reports. Home Assistant pulls from
it — nothing pushes into HA, and there's nothing new to keep online besides
WeeWX itself. The one exception is opt-in: if you point the forecast at a
Home Assistant pressure sensor (see below), WeeWX also reads from Home
Assistant's REST API.

## 1. Install the WeeWX skin

Requires WeeWX to already be running somewhere, with its reports served by
a web server (Apache/nginx/lighttpd) pointed at WeeWX's `public_html`
directory — the usual WeeWX setup for viewing the stock Seasons report.

Use `deploy.sh`, which packages the committed tree and installs it either on
this machine or over SSH:

```bash
./deploy.sh                            # install on this machine
./deploy.sh --host pi@weather.local    # install on a remote WeeWX host
./deploy.sh --host pi@weather.local -n # dry run: show every step, change nothing
```

It detects WeeWX 4 vs 5, uses `sudo` only if WeeWX is root-owned, restarts
the service and checks it came back, and clears the stale search-list file
left by 0.1.0. A remote deploy shares one multiplexed SSH connection, so it
asks for your credentials once rather than once per step.

Add `--configure` and it asks for everything the skin needs — units, the
forecast settings, and the optional Home Assistant pressure source including
how to treat its TLS certificate — then writes it into `weewx.conf` for you. Secrets are never written into
`weewx.conf`: the access token goes into a mode-600 file beside it,
referenced as `token_file`. Press Enter at any prompt to keep the current
value.

```bash
./deploy.sh --host pi@weather.local --configure
``` Add `--url http://<host>/weewxha/weewxha.json` to fetch and
validate the feed afterwards. Run `./deploy.sh --help` for the rest.

Reinstalling never overwrites your `weewx.conf` settings — WeeWX merges the
extension's stanza with `conditional_merge`, which only fills in keys that
aren't already there.

To install by hand instead, clone this repo onto the WeeWX host and run:

```bash
# WeeWX 5.x
weectl extension install /path/to/weewxha

# WeeWX 4.x
wee_extension --install /path/to/weewxha
```

This adds a `[StdReport][[weewxha]]` stanza to `weewx.conf` and drops the
skin into `skins/weewxha`. Restart WeeWX (or wait for the next report cycle)
and you should get:

- `http://<weewx-host>/weewxha/index.html` — the dashboard
- `http://<weewx-host>/weewxha/weewxha.json` — the data feed for Home Assistant

If WeeWX isn't behind a web server yet, point one at its `HTML_ROOT`
(`public_html` by default), or run something minimal like
`python3 -m http.server --directory /path/to/public_html 8000` for testing.

### Changing units

By default the skin reports in US customary units (°F, inHg, mph, inches).
To change it, edit the generated stanza in `weewx.conf`:

```ini
[StdReport]
    [[weewxha]]
        skin = weewxha
        HTML_ROOT = weewxha
        [[[Units]]]
            [[[[Groups]]]]
                group_temperature = degree_C
                group_pressure = hPa
                group_speed = km_per_hour
                group_rain = mm
                group_rainrate = mm_per_hour
```

The HA integration reads the unit token WeeWX reports alongside each value,
so it adapts automatically — no integration-side config needed.

### Weather forecast

The skin computes a **Zambretti** forecast from your own barometer history —
no forecast service, no API key, nothing to go offline. Given sea-level
pressure, its trend over the last 3 hours, the season, and the wind
direction, it produces one of 26 short outlook phrases ("Fine weather",
"Unsettled, rain later", …). It's the algorithm from the 1915 Negretti &
Zambra slide rule, designed for a **single ~12 hour outlook** — reliability
falls off past that, and it is not a time-stepped forecast: there is no
hourly, 12h and 24h breakdown, and no predicted temperatures or rainfall.
Being a purely local pressure-based method, it also knows nothing about
weather systems approaching from elsewhere. For multi-period forecasts, use
a Home Assistant weather integration alongside it.

The radar pane embeds radar.weather.gov as it comes, with no settings
imposed — the same view you get by visiting the site. It is loaded by the
*viewing browser*, not by WeeWX, so the two need different network access.

`radar_mode` takes:

| Mode | Shows |
| --- | --- |
| `default` | the NWS's own view, centred on your station |
| `enhanced` | local single-site view centred on your station |
| `standard` | the station's regional composite page |
| `image` | the cached GIF loop |

The default sends only a centre and a zoom, nothing else. That matters more
than it sounds: naming an agenda id changes which product is displayed even
when no layer is given — `local` forces single-site super-resolution
reflectivity, which on a quiet day is mostly clear-air return from insects and
ground clutter, drawn as speckle across the map. Sending just the centre
leaves the NWS's own default product in place. `radar_zoom` defaults to 7.

WeeWX also keeps a local copy of the loop beside the dashboard, refreshed on
its own TTL. That copy is what gets shown when the live radar can't be
reached: `image` mode serves it directly, and the embedded views fall back to
it, labelled as cached, if the frame fails to load. It is the only radar that
survives the viewer having no internet, since it comes from the same web
server as the page.

It appears on the dashboard as a banner, in `weewxha.json` under
`"forecast"`, and in Home Assistant as four entities:

| Entity | Example | Notes |
| --- | --- | --- |
| Forecast | `Unsettled, rain later` | the phrase |
| Forecast Code | `R` | Zambretti letter code, `A`–`Z` |
| Pressure Trend | `falling` | `rising` / `steady` / `falling` |
| Pressure Change | `-0.12 inHg` | change over the trend window |
| Forecast Pressure | `29.92 inHg` | the reading the forecast used |
| Forecast Pressure Source | `station` | `station` or `homeassistant` |

When the station has no barometer of its own, the borrowed reading also fills
in the ordinary `barometer` entity, the same way a borrowed inside temperature
fills in `inTemp` — so the sensor you would reach for works, rather than
sitting at `unknown` while the real value hides in a differently named one.
The station's own barometer always wins where it has one, and
`Forecast Pressure Source` still says where the value came from.

Tune it in the generated `weewx.conf` stanza (all optional):

```ini
[StdReport]
    [[weewxha]]
        [[[Forecast]]]
            enable = true
            trend_period = 10800    # trend window, seconds
            baro_lower = 950.0      # expected local pressure range, hPa
            baro_upper = 1050.0
```

Narrowing `baro_lower`/`baro_upper` to the range your station actually sees
gives you the full spread of forecasts instead of only the middle ones.
Hemisphere is taken from your station latitude, so the seasonal correction
is right in the south too. The 26 phrases can be reworded or translated via
`[[[Forecast]]][[[[Texts]]]]` keyed by letter code — see `skin.conf`.

### History charts

The dashboard draws a chart per observation from WeeWX's archive, plus one for
the forecast's own pressure — which for a Home Assistant source never reaches
the archive at all. Choose what is charted in the `[[[History]]]` section:

```ini
            observations = outTemp, outHumidity, barometer, windSpeed, rain
```

Any WeeWX observation type works. One your station doesn't record simply
produces no chart, the same way it gets no Home Assistant entity. Rain is
totalled over each interval and gusts taken at their peak rather than
averaged. Wind direction is refused: it is circular, so averaging 350° and
10° gives south — wrong rather than merely imprecise.

Until there's 3 hours of archive history, the trend is unknown: the forecast
still appears (computed from the steady-pressure table), but the trend and
pressure-change fields are omitted from the feed.

### Taking the pressure from a Home Assistant sensor

If your station has no barometer, the skin can read the pressure from a Home
Assistant sensor instead — a BME280, another weather integration, anything
that reports pressure. This is the one place data flows *into* WeeWX, so
WeeWX needs to reach Home Assistant and needs a long-lived access token
(Home Assistant: profile → Security → Long-lived access tokens).

```ini
[StdReport]
    [[weewxha]]
        [[[Forecast]]]
            [[[[HomeAssistant]]]]
                enable = true
                url = http://homeassistant.local:8123
                entity_id = sensor.outdoor_pressure
                token_file = /etc/weewx/ha_token
                timeout = 10
```

Prefer `token_file` over an inline `token`: `weewx.conf` is usually
world-readable, so a token in it is readable by every user on the machine.
Keep the token file mode `600` and owned by **the user `weewxd` runs as**
(usually `weewx`) — not root. `weewx.conf` is typically root-owned and
world-readable, so a root-owned mode-600 token beside it is one WeeWX cannot
read. `deploy.sh --configure` works this out from the systemd unit and sets
it for you.


If Home Assistant is behind `https` with a certificate from a private CA —
normal on an internal network — verification will fail. Best fix is to add
that CA to the host's trust store (`/usr/local/share/ca-certificates/` then
`update-ca-certificates`), which fixes every tool on the box. Otherwise point
the skin at it:

```ini
                ca_file = /etc/ssl/certs/internal-ca.pem
```

`verify = false` skips the check entirely, but the access token then travels
over a connection anything on the path can intercept — treat it as a last
resort. It logs a warning each time WeeWX starts.

Two things to know:

- **Sea-level or absolute?** Zambretti needs sea-level pressure — what WeeWX
  calls *barometer*. Many cheap sensors report the absolute pressure where
  they sit, which at any altitude reads low: about 27 hPa at 770 ft. That is
  enough to move the forecast into the wrong band, with nothing on the page to
  reveal it. Set `pressure_type = absolute` and the reading is reduced to sea
  level using your station altitude and outside temperature, via WeeWX's own
  conversion — so it matches what WeeWX would derive for a real barometer.
- **The trend needs its own history.** WeeWX's archive never saw this
  pressure, so each reading is appended to a small JSON file next to the
  WeeWX database (`weewxha_pressure.json`, override with `history_file`).
  Old samples are pruned automatically. After setup it takes a full
  `trend_period` before the trend appears.

### Inside temperature and humidity

The same block can supply indoor readings, for a station with no console
sensors:

```ini
                inside_temperature_entity_id = sensor.living_room_temperature
                inside_humidity_entity_id = sensor.living_room_humidity
```

Each is independent — set either, both or neither. They are converted into the
skin's own units, appear as the usual `inTemp`/`inHumidity` entities in Home
Assistant, and are labelled on the dashboard as coming from Home Assistant.
Your station's own sensors always win where it has them.

The unit is read from the entity's `unit_of_measurement` (Pa, hPa, mbar,
kPa, bar, cbar, mmHg, inHg, psi); set `unit` explicitly only if the entity
has none. When Home Assistant is configured it takes precedence over the
station barometer; if a fetch fails, the skin logs a warning and falls back
to the station barometer, so an outage degrades the forecast rather than
stopping it. `Forecast Pressure Source` tells you which one was used —
useful for confirming the setup works.

## 2. Install the Home Assistant integration

**Via HACS**: add this repo as a custom repository (category: Integration),
then install "WeeWX-HA".

**Manually**: copy `custom_components/weewxha` into your Home Assistant
config's `custom_components/` directory and restart Home Assistant.

Then, in Home Assistant: **Settings → Devices & Services → Add Integration
→ WeeWX-HA**, and enter the `weewxha.json` URL from step 1.

If WeeWX is served over `https` with a certificate from a private CA — normal
on an internal network — untick **Verify the TLS certificate**. Home Assistant
will not trust that CA and, unlike a browser, offers no way to click through;
the setup simply fails to connect. Leave it ticked for a public certificate or
plain `http`. A device is
created for the station, with one sensor entity per observation your
station reports (temperature, humidity, barometer, wind, rain, the forecast,
and — if present — UV, solar radiation, console battery voltage, signal
quality, and battery-low status).

Alongside those is **Report Generated**, a timestamp of when WeeWX last built
the feed — not when Home Assistant last fetched it. A stopped WeeWX keeps
serving its last report, and the poll goes on succeeding; this is the entity
an automation watches to notice that the data has stopped moving.

With the National Weather Service enabled you also get:

| Entity | State | Attributes |
| --- | --- | --- |
| `weather.<station>` | current conditions | 7-day forecast, `forecast_text` |
| Weather Alerts | number in force | every alert, plus the most severe one's `headline`, `description`, `instruction`, `area`, timings and `url` |
| Forecast Text | this period's narrative | all periods as prose, office, staleness |
| Radar | radar site id | loop, enhanced and page URLs |

The weather entity is the idiomatic one — Home Assistant's weather card and
anything consuming forecasts understand it directly, rather than having to
reassemble a forecast from separate sensors.

Two deliberate choices there. The alerts sensor exists whenever the NWS is
configured, sitting at `0` when nothing is in force, because an automation
watching for "more than zero" needs an entity to watch rather than one that
appears with the first warning. And long text lives in attributes, not states:
Home Assistant caps a state at 255 characters, which an alert headline alone
can exceed.

### Acting on alerts

Substitute your own entity id throughout — with `has_entity_name` the alerts
sensor lands at `sensor.<station>_weather_alerts`, where the station is the
config entry's title — and your own notify target, since `notify.notify`
reaches everything you have configured.

`severity` is the National Weather Service's own classification, passed
through untouched, and it is stingier than instinct: a Tornado Warning is
`Extreme`, but a Severe Thunderstorm Warning is only `Severe`, and most flood
warnings with it. `["Extreme", "Severe"]` is the useful definition of
dangerous; `Extreme` alone is a much smaller set than it sounds.

**Is anything extreme in force?**

```jinja
{{ state_attr('sensor.weather_alerts', 'alerts')
   | default([], true)
   | selectattr('severity', 'eq', 'Extreme')
   | list | count > 0 }}
```

The `default([], true)` is not decoration. Before the first poll, and whenever
a poll fails, the attribute is absent and `selectattr` would raise; with it the
template renders `false` and fails safe.

Scanning the list is worth the extra line over the shorter
`state_attr('sensor.weather_alerts', 'highest_severity') == 'Extreme'`. That
one is correct only because the skin sorts worst-first, so it depends on
something a template can't see.

**Notifying on dangerous weather, and on the all-clear.**

The trigger watches the `alerts` attribute rather than the sensor's state,
because the state is a count: when a Moderate advisory is replaced by an
Extreme warning it stays at `1`, and a trigger on the state never fires.

```yaml
automation:
  - id: dangerous_weather_approaching
    alias: Dangerous weather approaching
    description: >-
      Notify when the NWS issues an Extreme or Severe alert for the station,
      once per alert, and again when the last one lifts.
    mode: queued
    max: 5
    triggers:
      - trigger: state
        entity_id: sensor.weather_alerts
        attribute: alerts
    variables:
      danger: ["Extreme", "Severe"]
      # A failed poll marks the sensor unavailable, which drops its attributes
      # entirely -- that must not read as "the warning lifted".
      live: "{{ trigger.to_state.state not in ['unavailable', 'unknown'] }}"
      before: >-
        {{ (trigger.from_state.attributes.alerts if trigger.from_state else [])
           | default([], true) | selectattr('severity', 'in', danger) | list }}
      active: >-
        {{ (trigger.to_state.attributes.alerts if trigger.to_state else [])
           | default([], true) | selectattr('severity', 'in', danger) | list }}
      # Lesser alerts still standing after the dangerous ones lift.
      remaining: >-
        {{ (trigger.to_state.attributes.alerts if trigger.to_state else [])
           | default([], true) | rejectattr('severity', 'in', danger) | list }}
      # Matched on id, so a re-issued description or refreshed expiry time
      # doesn't notify twice.
      fresh: "{{ active | rejectattr('id', 'in', before | map(attribute='id') | list) | list }}"
      cleared: "{{ before | rejectattr('id', 'in', active | map(attribute='id') | list) | list }}"
      # The skin sorts worst-first, so the head of the list leads.
      alert: "{{ fresh[0] if fresh else none }}"
    actions:
      - choose:
          # -- something dangerous has arrived ---------------------------
          - conditions:
              - condition: template
                value_template: "{{ live and fresh | count > 0 }}"
            sequence:
              - action: notify.notify
                data:
                  title: "⚠️ {{ alert.event }}{% if alert.area %} — {{ alert.area }}{% endif %}"
                  message: >-
                    {{ alert.headline or alert.event }}.
                    {%- if alert.expires_label %} In effect until {{ alert.expires_label }}.{% endif %}
                    {%- if alert.instruction %} {{ alert.instruction }}{% endif %}
                    {%- if fresh | count > 1 %} ({{ fresh | count - 1 }} other alert(s) also issued.){% endif %}
                  data:
                    url: "{{ alert.url }}"
          # -- the last dangerous alert has lifted ------------------------
          - conditions:
              - condition: template
                value_template: "{{ live and before | count > 0 and active | count == 0 }}"
            sequence:
              - action: notify.notify
                data:
                  title: "✅ All clear"
                  message: >-
                    {{ cleared | map(attribute='event') | unique | list | join(', ') }}
                    no longer in effect.
                    {%- if remaining %} {{ remaining | map(attribute='event') | unique | list | join(', ') }} still in force.{% endif %}
```

Three things in there are load-bearing:

- **The `live` guard.** A failed poll makes every entity unavailable, and an
  unavailable entity drops its attributes — which looks exactly like the alert
  list emptying. Without the guard, WeeWX stopping during a tornado warning
  sends an all-clear.
- **Matching on `id`, not on counts.** The NWS re-issues an alert with an
  updated description or expiry as the same `id`, which would otherwise notify
  again each poll.
- **All-clear on the *dangerous* set emptying, not the alert list.** An Extreme
  warning expiring while a Severe one continues is not all clear, and stays
  silent; a lesser advisory still standing doesn't suppress the all-clear, it
  just gets a mention.

The one case with no good answer is a Home Assistant restart during an active
warning: nothing survives to compare against, so the warning looks new and
notifies twice. That is the deliberate choice here — a duplicate beats a missed
tornado warning. To take the silence instead, add
`{{ trigger.from_state is not none }}` as a condition on the first branch; the
all-clear compares against the last good state and is unaffected either way.

The message uses `headline` and `instruction` rather than `description`: the
description is the forecaster's full write-up and routinely runs to several
hundred characters, while `instruction` is the "what to do about it". Add
`{{ alert.description }}` if you want the lot — a mobile notification will
take it.

### Noticing a stopped feed

This is what **Report Generated** is for. When WeeWX stops, the web server
keeps serving the last report it wrote: the poll succeeds, every sensor holds
its final reading, and nothing anywhere goes unavailable. A dashboard of
plausible, motionless numbers is the failure mode worth catching.

Fifteen minutes below assumes the default five-minute archive interval — three
missed reports, which is a stop rather than a hiccup. Scale it to your own
interval.

```yaml
template:
  - binary_sensor:
      - name: Weather feed stale
        unique_id: weewxha_feed_stale
        device_class: problem
        # Ride out a single missed report, and the gap at startup before the
        # first poll has landed.
        delay_on: "00:02:00"
        state: >-
          {{ not has_value('sensor.report_generated')
             or now() - states('sensor.report_generated') | as_datetime
                > timedelta(minutes=15) }}

automation:
  - id: weewx_feed_stopped
    alias: WeeWX feed has stopped updating
    mode: single
    triggers:
      - trigger: state
        entity_id: binary_sensor.weather_feed_stale
        to: "on"
        id: stale
      - trigger: state
        entity_id: binary_sensor.weather_feed_stale
        to: "off"
        id: recovered
    actions:
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ trigger.id == 'stale' }}"
            sequence:
              - action: notify.notify
                data:
                  title: "Weather feed has stopped"
                  message: >-
                    {%- set last = states('sensor.report_generated') | as_datetime %}
                    {% if last %}No new weather report for {{ relative_time(last) }}
                    (the last one was {{ (last | as_local).strftime('%-I:%M %p') }}).
                    {%- else %}The weather feed is unreachable.{% endif %}
                    Check that WeeWX is running and its report cycle is publishing.
          - conditions:
              - condition: template
                value_template: "{{ trigger.id == 'recovered' }}"
            sequence:
              - action: notify.notify
                data:
                  title: "Weather feed is back"
                  message: >-
                    Reports are arriving again
                    {%- set last = states('sensor.report_generated') | as_datetime %}
                    {%- if last %} (latest {{ (last | as_local).strftime('%-I:%M %p') }}){% endif %}.
```

Note the `not has_value(...)` at the front, which is the opposite of the guard
in the alerts automation above. There, an unavailable sensor had to be treated
as "no news" so a failed poll couldn't fake an all-clear. Here an unreachable
feed *is* the thing being watched for — WeeWX down and Home Assistant unable to
reach it are the same problem to whoever gets the notification — so it counts
as stale, and the message distinguishes the two cases anyway. `delay_on` keeps
that from firing during the unknown gap at startup.

## Repo layout

```
bin/user/                 Python installed into WeeWX's user directory
  weewxha_search.py       search-list extension (JSON-safe values, forecast)
  weewxha_forecast.py     Zambretti forecast algorithm (no WeeWX imports)
  weewxha_ha.py           optional pressure source: reads a Home Assistant
                          sensor, keeps a rolling history for the trend
skins/weewxha/            WeeWX skin (install.py packages this as an extension)
  skin.conf
  index.html.tmpl         human dashboard
  weewxha.json.tmpl       HA data feed
  static/weewxha.css
custom_components/weewxha/  Home Assistant custom integration
  manifest.json
  config_flow.py          UI setup: prompts for the feed URL
  coordinator.py          polls weewxha.json on an interval
  sensor.py / binary_sensor.py   dynamic entities from whatever fields are present
  units.py                WeeWX unit token -> HA unit/device_class mapping
deploy.sh                  packages and installs the skin, locally or over SSH
install.py                 WeeWX extension installer entry point
hacs.json                  HACS metadata
```

## Status

Early — core plumbing (skin templates, search list extension, forecast,
config flow, coordinator, dynamic entity creation) is in place.

The skin has been run under WeeWX 5.4 against a synthetic archive database:
report generation, `weewxha.json`, the dashboard, and the forecast were
verified across the US/Metric/MetricWX unit presets, both hemispheres, and
the degraded cases (no barometer, less than a trend window of history,
forecast disabled). The Home Assistant pressure source was verified against
a stand-in REST API — unit conversions, trend from the rolling history,
fallback to the station barometer when the fetch fails, and the bad
token / missing entity / unavailable-state / unreachable-host paths — but
not yet against a real Home Assistant.

The integration itself has been loaded into a running Home Assistant, and the
entity discovery and state logic were exercised there against real generated
feeds. The skin has **not** yet been run against live station hardware — only
against the synthetic archive above — so before relying on it, install both
halves and confirm the feed renders from your own station and the config flow
creates the entities you expect.

Before publishing: `codeowners` in
`custom_components/weewxha/manifest.json` is still empty. The `documentation`
and `issue_tracker` URLs point at this repo's own remote, which is correct for
an internal install but would need changing if it ever moves to a public host.
