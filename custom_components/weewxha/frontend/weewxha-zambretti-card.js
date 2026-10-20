// The skin's Zambretti panel as a Lovelace card.
//
// Reads one entity, the Zambretti "Forecast" sensor, whose attributes carry
// the rest of the panel: code, condition, the pressure the forecast used and
// its trend, already formatted by the skin in its own unit. Served by the
// integration itself, so there is nothing to add under Dashboard resources.
//
// Laid out like Home Assistant's own weather forecast card (the current
// conditions row of hui-weather-forecast-card), with the same sizes, spacing
// and theme variables, so the two sit together in a stack.
//
//   type: custom:weewxha-zambretti-card
//   entity: sensor.<station>_forecast

// Glyph and the weather-icon colour Home Assistant paints that condition in.
// Its card draws its own coloured artwork, which a custom card cannot reach;
// tinting the MDI glyph with the same theme variables is the nearest match.
const SUN = "var(--weather-icon-sun-color, #fdd93c)";
const CLOUD = "var(--weather-icon-cloud-back-color, #d4d4d4)";
const RAIN = "var(--weather-icon-rain-color, #30b3ff)";
const SNOW = "var(--weather-icon-snow-color, #f9f9f9)";
const CONDITION_ICONS = {
  sunny: ["mdi:weather-sunny", SUN],
  "clear-night": ["mdi:weather-night", "var(--weather-icon-moon-color, #fcf497)"],
  partlycloudy: ["mdi:weather-partly-cloudy", SUN],
  cloudy: ["mdi:weather-cloudy", CLOUD],
  rainy: ["mdi:weather-rainy", RAIN],
  pouring: ["mdi:weather-pouring", RAIN],
  lightning: ["mdi:weather-lightning", SUN],
  "lightning-rainy": ["mdi:weather-lightning-rainy", RAIN],
  snowy: ["mdi:weather-snowy", SNOW],
  fog: ["mdi:weather-fog", CLOUD],
  windy: ["mdi:weather-windy", CLOUD],
};

const STYLE = `<style>
  ha-card {
    cursor: pointer;
    outline: none;
    padding: 16px;
    height: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .content {
    display: flex;
    flex-wrap: nowrap;
    justify-content: space-between;
    align-items: center;
  }
  .icon-image {
    display: flex;
    align-items: center;
    min-width: 64px;
    margin-inline-end: 16px;
  }
  ha-icon { --mdc-icon-size: 64px; }
  .info {
    display: flex;
    justify-content: space-between;
    flex-grow: 1;
    overflow: hidden;
  }
  .name-state {
    overflow: hidden;
    padding-inline-end: 12px;
    width: 100%;
  }
  .state, .value {
    font-size: 28px;
    line-height: 1.2;
  }
  .name, .attribute {
    font-size: 14px;
    line-height: 1;
    color: var(--secondary-text-color);
  }
  .name {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  /* The weather card truncates its one-word condition; a Zambretti phrase
     runs to several words and is the whole point, so it wraps instead. */
  .state { margin-bottom: 2px; }
  .reading { text-align: end; align-self: flex-start; }
  .value { white-space: nowrap; }
  .value .unit { font-size: 16px; }
  .attribute { white-space: nowrap; }
  .unavailable {
    color: var(--secondary-text-color);
    font-size: 14px;
  }
</style>`;

const escape = (text) =>
  String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

class WeewxHaZambrettiCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Set entity to the Zambretti Forecast sensor");
    }
    this._config = config;
    this._key = null;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      // Like the weather card, a tap opens the entity's more-info dialog.
      this.addEventListener("click", () => {
        const event = new Event("hass-more-info", { bubbles: true, composed: true });
        event.detail = { entityId: this._config.entity };
        this.dispatchEvent(event);
      });
    }
  }

  set hass(hass) {
    const state = hass.states[this._config.entity];
    // Only redraw when the entity actually changed, not on every HA update.
    const key = state ? state.last_updated : "missing";
    if (key === this._key) return;
    this._key = key;
    this.shadowRoot.innerHTML = STYLE + this._render(state);
  }

  _render(state) {
    if (!state || ["unavailable", "unknown"].includes(state.state)) {
      const why = state ? "No forecast yet" : `Entity not found: ${this._config.entity}`;
      return `<ha-card><div class="unavailable">${escape(why)}</div></ha-card>`;
    }

    const a = state.attributes;
    const [icon, colour] = CONDITION_ICONS[a.condition] ||
      ["mdi:weather-partly-cloudy", SUN];

    // Under the phrase, where the weather card puts the entity's name.
    let name = escape(this._config.name || "Zambretti");
    if (a.code) name += ` ${escape(a.code)}`;
    name += ` · ~${escape(a.horizon_hours || 12)} h`;

    // On the right, where the weather card puts the temperature and one
    // attribute: the pressure the forecast used, and which way it is going.
    let reading = "";
    if (a.pressure !== undefined || a.pressure_trend) {
      const value = a.pressure !== undefined
        ? `${escape(a.pressure)}<span class="unit">&nbsp;${escape(a.pressure_unit || "")}</span>`
        : "";
      // The arrow already says rising or falling; the word is the fallback.
      let trend = "";
      if (a.pressure_change) {
        trend = `${escape(a.trend_arrow || a.pressure_trend || "")} ${escape(a.pressure_change)}`;
        if (a.trend_hours) trend += ` / ${escape(a.trend_hours)} h`;
      } else if (a.pressure_trend) {
        trend = `${escape(a.trend_arrow || "")} ${escape(a.pressure_trend)}`;
      }
      reading = `<div class="reading">
        <div class="value">${value}</div>
        <div class="attribute">${trend.trim()}</div>
      </div>`;
    }

    return `<ha-card>
      <div class="content">
        <div class="icon-image">
          <ha-icon icon="${escape(icon)}" style="color: ${colour}"></ha-icon>
        </div>
        <div class="info">
          <div class="name-state">
            <div class="state">${escape(state.state)}</div>
            <div class="name">${name}</div>
          </div>
          ${reading}
        </div>
      </div>
    </ha-card>`;
  }

  getCardSize() {
    return 2;
  }

  static getStubConfig(hass) {
    // horizon_hours is set only on this integration's Zambretti sensor.
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("sensor.") && "horizon_hours" in hass.states[id].attributes,
    );
    return { entity: entity || "sensor.weewx_forecast" };
  }
}

// Home Assistant's app replaces window.customElements with a scoped-registry
// polyfill as it starts, and as an extra module this file can run before
// that. A card defined on the original registry is then invisible to the
// dashboard: listed in the picker, but "Custom element not found". Waiting
// for <home-assistant> to be defined means the polyfill is in place, and the
// customElements looked up at that point is the one the dashboard uses.
customElements.whenDefined("home-assistant").then(() => {
  if (customElements.get("weewxha-zambretti-card")) return;
  customElements.define("weewxha-zambretti-card", WeewxHaZambrettiCard);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "weewxha-zambretti-card",
    name: "WeeWX Zambretti",
    description: "The local Zambretti outlook, styled like the weather forecast card.",
  });
});
