/*
 * Home Modes Advanced - Lovelace cards (plain JavaScript, no build step, no external requests).
 *
 *   custom:home-modes-card        full switcher (status, modes, overlays, Auto, temporary)
 *   custom:home-modes-guest-card  minimal card for a restricted dashboard
 *
 * Both cards read their state from the Home Modes select entity and get the list of roles
 * the CURRENT user may set from the server (websocket command home_modes/allowed_roles).
 * Hiding a button is only a convenience: the services and entities enforce permissions on
 * the server, whatever a card shows.
 *
 * All text that comes from the server (role names) is written with textContent or
 * setAttribute, never with innerHTML.
 */
const HM_VERSION = "0.9.1";
const DOMAIN = "home_modes";
const WS_ALLOWED = "home_modes/allowed_roles";
const ICON_RE = /^[a-z0-9_-]+:[a-z0-9_-]+$/i;
const DEFAULT_ICON = "mdi:home-automation";
const TEMPORARY_CHOICES = [30, 60, 120, 240]; // minutes
const ERROR_MS = 8000;
const TICK_MS = 30000;

const TEXT = {
  not_loaded: "Home Modes is not loaded. Check Settings > Devices & services.",
  no_entity: "The Home Modes entity was not found.",
  loading: "Loading...",
  auto_on: "Auto on",
  auto_off: "Auto off",
  auto_button: "Auto",
  since: "since",
  override_until: "Manual change until",
  override_next_auto: "Manual change until the next automatic change",
  override_set_auto: "Manual change until you press Auto",
  temporary: "Temporary, back to",
  at: "at",
  denied: "Not allowed",
  failed: "That did not work",
  none_allowed: "No modes are available for you.",
  for_label: "For",
  for_forever: "Until I change it",
  overlays: "Also",
  minutes: "min",
  hours: "h",
};

const clean = (value, fallback) => (typeof value === "string" && ICON_RE.test(value) ? value : fallback);

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "text") node.textContent = value;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children) if (child) node.append(child);
  return node;
}

function relativeText(iso, now) {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const seconds = Math.round((then - now) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto", style: "short" });
  const abs = Math.abs(seconds);
  if (abs < 60) return formatter.format(seconds, "second");
  if (abs < 3600) return formatter.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return formatter.format(Math.round(seconds / 3600), "hour");
  return formatter.format(Math.round(seconds / 86400), "day");
}

function clockText(iso) {
  const date = new Date(iso);
  return Number.isFinite(date.getTime())
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";
}

function durationLabel(minutes) {
  return minutes % 60 === 0 && minutes >= 60 ? `${minutes / 60} ${TEXT.hours}` : `${minutes} ${TEXT.minutes}`;
}

const STYLE = `
  :host { display: block; }
  ha-card { padding: 12px 16px 16px; }
  .title { font-size: var(--ha-card-header-font-size, 20px); font-weight: 500; padding: 4px 0 8px; color: var(--primary-text-color); }
  .status { display: flex; align-items: center; gap: 12px; padding: 4px 0 12px; }
  .status ha-icon { --mdc-icon-size: 32px; color: var(--primary-color); flex: none; }
  .status .now { font-size: 1.25em; font-weight: 500; color: var(--primary-text-color); overflow-wrap: anywhere; }
  .status .sub, .notes { color: var(--secondary-text-color); font-size: 0.875em; }
  .notes { padding: 0 0 8px; display: grid; gap: 4px; }
  .group { display: flex; flex-wrap: wrap; gap: 8px; padding: 4px 0; }
  .label { color: var(--secondary-text-color); font-size: 0.8125em; padding: 8px 0 2px; }
  button, select {
    font: inherit; color: var(--primary-text-color); background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color); border-radius: var(--ha-card-border-radius, 12px);
    min-height: 44px; min-width: 44px; padding: 8px 14px; cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    touch-action: manipulation; -webkit-tap-highlight-color: transparent;
  }
  .group button { flex: 1 1 120px; }
  .compact .group button { flex: 0 1 auto; }
  button ha-icon { --mdc-icon-size: 20px; }
  button[aria-pressed="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  button:active { opacity: 0.8; }
  button:focus-visible, select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  button[disabled], select[disabled] { opacity: 0.5; cursor: default; }
  .error, .message { padding: 8px 0 0; font-size: 0.9375em; }
  .error { color: var(--error-color, #db4437); }
  .message { color: var(--secondary-text-color); }
`;

class HomeModesBase extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = undefined;
    this._allowed = undefined; // {modes, overlays, can_set_auto} or {error}
    this._signature = "";
    this._busy = false;
    this._error = "";
    this._errorTimer = undefined;
    this._tick = undefined;
    this._duration = 0; // minutes, 0 = until changed
    this._onVisible = () => {
      if (document.visibilityState === "visible") this._loadAllowed();
    };
  }

  // --- defaults: subclasses override ---------------------------------------
  static get defaults() {
    return {};
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    const roles = config.roles;
    if (roles !== undefined && !(Array.isArray(roles) && roles.every((r) => typeof r === "string"))) {
      throw new Error("roles must be a list of role ids");
    }
    this._config = { ...this.constructor.defaults, ...config };
    this._render();
  }

  getCardSize() {
    return this._config.layout === "compact" ? 2 : 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  set hass(hass) {
    const first = this._hass === undefined;
    this._hass = hass;
    const select = this._select();
    const signature = select ? JSON.stringify(select.attributes.options || []) : "";
    if (first || signature !== this._signature) {
      this._signature = signature;
      this._loadAllowed();
    }
    this._render();
  }

  connectedCallback() {
    document.addEventListener("visibilitychange", this._onVisible);
    this._tick = window.setInterval(() => this._render(), TICK_MS);
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisible);
    window.clearInterval(this._tick);
    window.clearTimeout(this._errorTimer);
  }

  // --- data -------------------------------------------------------------------
  _select() {
    const hass = this._hass;
    if (!hass) return undefined;
    const wanted = this._config.entity;
    if (wanted) return hass.states[wanted];
    if (this._entityId && hass.states[this._entityId]) return hass.states[this._entityId];
    for (const [id, state] of Object.entries(hass.states)) {
      const attrs = state.attributes || {};
      if (id.startsWith("select.") && typeof attrs.mode_id === "string" && Array.isArray(attrs.overlays)) {
        this._entityId = id;
        return state;
      }
    }
    return undefined;
  }

  async _loadAllowed() {
    if (!this._hass) return;
    try {
      this._allowed = await this._hass.callWS({ type: WS_ALLOWED });
    } catch (err) {
      this._allowed = { error: err && err.code === "not_found" ? "not_loaded" : "failed" };
    }
    this._render();
  }

  // The server list, narrowed (never widened) by the card configuration.
  _visible(list) {
    const subset = this._config.roles;
    return (list || []).filter((role) => !subset || subset.includes(role.id));
  }

  _icon(role) {
    const custom = this._config.icons && this._config.icons[role.id];
    return clean(custom, clean(role.icon, DEFAULT_ICON));
  }

  // --- actions ----------------------------------------------------------------
  async _call(service, data) {
    if (this._busy) return;
    this._busy = true;
    this._setError("");
    this._render();
    try {
      await this._hass.callService(DOMAIN, service, data);
    } catch (err) {
      const message = err && err.message ? String(err.message) : "";
      this._setError(message || TEXT.failed);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _setError(message) {
    this._error = message;
    window.clearTimeout(this._errorTimer);
    if (message) this._errorTimer = window.setTimeout(() => this._setError("") || this._render(), ERROR_MS);
  }

  _pickMode(role) {
    if (this._duration > 0 && this._config.show_temporary) {
      const hours = String(Math.floor(this._duration / 60)).padStart(2, "0");
      const minutes = String(this._duration % 60).padStart(2, "0");
      this._call("set_temporary", { mode: role.id, duration: `${hours}:${minutes}:00` });
    } else {
      this._call("set_mode", { mode: role.id });
    }
  }

  // --- rendering --------------------------------------------------------------
  _button(role, pressed, onClick) {
    const button = el(
      "button",
      { type: "button", "aria-pressed": pressed ? "true" : "false", disabled: this._busy },
      el("ha-icon", { icon: this._icon(role) }),
      el("span", { text: role.name }),
    );
    button.addEventListener("click", onClick);
    return button;
  }

  _statusBlock(select, allowed) {
    const attrs = select.attributes;
    const now = Date.now();
    const current = [...(allowed.modes || [])].find((r) => r.id === attrs.mode_id);
    const name = current ? current.name : select.state;
    const icon = current ? this._icon(current) : clean(undefined, DEFAULT_ICON);
    const wrap = el("div", { class: "status", "aria-live": "polite" });
    const text = el("div", {}, el("div", { class: "now", text: name }));
    const sub = [];
    if (attrs.since) sub.push(`${TEXT.since} ${relativeText(attrs.since, now)}`);
    if (this._config.show_auto) sub.push(attrs.auto ? TEXT.auto_on : TEXT.auto_off);
    text.append(el("div", { class: "sub", text: sub.join(" · ") }));
    wrap.append(el("ha-icon", { icon }), text);
    const notes = el("div", { class: "notes" });
    const override = attrs.override;
    if (override) {
      let line = TEXT.override_next_auto;
      if (override.until) line = `${TEXT.override_until} ${clockText(override.until)} (${relativeText(override.until, now)})`;
      else if (override.mode === "set_auto") line = TEXT.override_set_auto;
      notes.append(el("div", { text: line }));
    }
    const temporary = attrs.temporary;
    if (temporary) {
      const back = temporary.revert_to_name || temporary.revert_to;
      notes.append(el("div", { text: `${TEXT.temporary} ${back} ${TEXT.at} ${clockText(temporary.until)} (${relativeText(temporary.until, now)})` }));
    }
    return [wrap, notes.childNodes.length ? notes : null];
  }

  _render() {
    const root = this.shadowRoot;
    const cfg = this._config;
    const card = el("ha-card", { class: cfg.layout === "compact" ? "compact" : "full" });
    if (cfg.title) card.append(el("div", { class: "title", text: cfg.title }));

    const select = this._select();
    const allowed = this._allowed;
    if (!this._hass || allowed === undefined) {
      card.append(el("div", { class: "message", text: TEXT.loading }));
    } else if (allowed.error === "not_loaded") {
      card.append(el("div", { class: "error", role: "alert", text: TEXT.not_loaded }));
    } else if (allowed.error) {
      card.append(el("div", { class: "error", role: "alert", text: TEXT.failed }));
    } else if (!select) {
      card.append(el("div", { class: "error", role: "alert", text: TEXT.no_entity }));
    } else {
      this._renderBody(card, select, allowed);
    }
    if (this._error) card.append(el("div", { class: "error", role: "alert", text: this._error }));
    root.replaceChildren(el("style", { text: STYLE }), card);
  }

  _renderBody(card, select, allowed) {
    const cfg = this._config;
    const attrs = select.attributes;
    const modes = this._visible(allowed.modes);
    const overlays = cfg.show_overlays ? this._visible(allowed.overlays) : [];
    if (cfg.show_status) for (const node of this._statusBlock(select, allowed)) if (node) card.append(node);

    if (!modes.length && !overlays.length) {
      card.append(el("div", { class: "message", text: TEXT.none_allowed }));
    }
    if (modes.length) {
      if (cfg.show_temporary) card.append(this._durationPicker());
      const group = el("div", { class: "group", role: "group" });
      for (const role of modes) group.append(this._button(role, attrs.mode_id === role.id, () => this._pickMode(role)));
      card.append(group);
    }
    if (overlays.length) {
      if (cfg.layout !== "compact") card.append(el("div", { class: "label", text: TEXT.overlays }));
      const group = el("div", { class: "group", role: "group" });
      for (const role of overlays) {
        const active = (attrs.overlays || []).includes(role.id);
        group.append(this._button(role, active, () => this._call("set_overlay", { overlay: role.id, active: !active })));
      }
      card.append(group);
    }
    if (cfg.show_auto && allowed.can_set_auto) {
      const auto = el(
        "button",
        { type: "button", "aria-pressed": "false", disabled: this._busy },
        el("ha-icon", { icon: "mdi:calendar-sync" }),
        el("span", { text: TEXT.auto_button }),
      );
      auto.addEventListener("click", () => this._call("set_auto", {}));
      card.append(el("div", { class: "group" }, auto));
    }
  }

  _durationPicker() {
    const select = el("select", { "aria-label": TEXT.for_label, disabled: this._busy });
    select.append(el("option", { value: "0", text: TEXT.for_forever }));
    for (const minutes of TEMPORARY_CHOICES) select.append(el("option", { value: String(minutes), text: durationLabel(minutes) }));
    select.value = String(this._duration);
    select.addEventListener("change", () => {
      this._duration = Number(select.value) || 0;
    });
    return el("div", { class: "group" }, el("span", { class: "label", text: TEXT.for_label }), select);
  }
}

class HomeModesCard extends HomeModesBase {
  static get defaults() {
    return { layout: "full", show_status: true, show_overlays: true, show_auto: true, show_temporary: false };
  }

  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return document.createElement("home-modes-card-editor");
  }
}

class HomeModesGuestCard extends HomeModesBase {
  // A guest card never shows Auto or the temporary control; those are not for guests.
  static get defaults() {
    return { layout: "compact", show_status: false, show_overlays: true, show_auto: false, show_temporary: false };
  }

  setConfig(config) {
    super.setConfig({ ...config, show_auto: false, show_temporary: false });
  }

  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return document.createElement("home-modes-guest-card-editor");
  }
}

// --- visual editors (ha-form is provided by the Home Assistant frontend) -----------

const LABELS = {
  title: "Title",
  layout: "Layout",
  roles: "Show only these modes (empty: all you may set)",
  show_status: "Show current mode and status",
  show_overlays: "Show overlays (Guest, Do not disturb)",
  show_auto: "Show the Auto button",
  show_temporary: "Show the temporary-mode control",
};

class HomeModesEditorBase extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = undefined;
    this._roles = [];
    this._loaded = false;
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      hass
        .callWS({ type: WS_ALLOWED })
        .then((result) => {
          this._roles = [...(result.modes || []), ...(result.overlays || [])];
          this._render();
        })
        .catch(() => this._render());
    }
    if (this._form) this._form.hass = hass;
  }

  // Which fields the editor offers; subclasses override.
  _fields() {
    return ["title", "layout", "roles"];
  }

  _schema() {
    const fields = this._fields();
    const schema = [];
    if (fields.includes("title")) schema.push({ name: "title", selector: { text: {} } });
    if (fields.includes("layout"))
      schema.push({
        name: "layout",
        selector: { select: { mode: "dropdown", options: [{ value: "compact", label: "Compact" }, { value: "full", label: "Full" }] } },
      });
    for (const name of ["show_status", "show_overlays", "show_auto", "show_temporary"]) {
      if (fields.includes(name)) schema.push({ name, selector: { boolean: {} } });
    }
    if (fields.includes("roles") && this._roles.length) {
      schema.push({
        name: "roles",
        selector: { select: { multiple: true, mode: "list", options: this._roles.map((r) => ({ value: r.id, label: r.name })) } },
      });
    }
    if (fields.includes("icons")) {
      for (const role of this._roles) schema.push({ name: `icon_${role.id}`, selector: { icon: {} } });
    }
    return schema;
  }

  _data() {
    const data = { ...this._config };
    for (const [id, icon] of Object.entries(this._config.icons || {})) data[`icon_${id}`] = icon;
    return data;
  }

  _label(schema) {
    if (schema.name.startsWith("icon_")) {
      const role = this._roles.find((r) => `icon_${r.id}` === schema.name);
      return `Icon for ${role ? role.name : schema.name.slice(5)}`;
    }
    return LABELS[schema.name] || schema.name;
  }

  _changed(event) {
    const value = { ...event.detail.value };
    const icons = { ...(this._config.icons || {}) };
    for (const key of Object.keys(value)) {
      if (!key.startsWith("icon_")) continue;
      const id = key.slice(5);
      if (value[key]) icons[id] = value[key];
      else delete icons[id];
      delete value[key];
    }
    for (const key of Object.keys(icons)) if (!this._roles.some((r) => r.id === key) && this._roles.length) delete icons[key];
    if (Object.keys(icons).length) value.icons = icons;
    else delete value.icons;
    if (Array.isArray(value.roles) && !value.roles.length) delete value.roles;
    this._config = value;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: value }, bubbles: true, composed: true }));
  }

  _render() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) => this._label(schema);
      this._form.addEventListener("value-changed", (event) => this._changed(event));
      this.append(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._data();
    this._form.schema = this._schema();
  }
}

class HomeModesCardEditor extends HomeModesEditorBase {
  _fields() {
    return ["title", "layout", "show_status", "show_overlays", "show_auto", "show_temporary", "roles", "icons"];
  }
}

class HomeModesGuestCardEditor extends HomeModesEditorBase {
  _fields() {
    return ["title", "layout", "show_overlays", "roles"];
  }
}

const REGISTRY = [
  ["home-modes-card", HomeModesCard],
  ["home-modes-guest-card", HomeModesGuestCard],
  ["home-modes-card-editor", HomeModesCardEditor],
  ["home-modes-guest-card-editor", HomeModesGuestCardEditor],
];
for (const [name, klass] of REGISTRY) if (!customElements.get(name)) customElements.define(name, klass);

window.customCards = window.customCards || [];
for (const card of [
  {
    type: "home-modes-card",
    name: "Home Modes",
    description: "Shows the current house mode and lets you change it (modes, overlays, Auto).",
  },
  {
    type: "home-modes-guest-card",
    name: "Home Modes (guest)",
    description: "Minimal card for a restricted dashboard: only the modes the signed-in user may set.",
  },
]) {
  if (!window.customCards.some((c) => c.type === card.type)) window.customCards.push({ ...card, preview: false });
}
console.info(`%c HOME-MODES-CARDS %c ${HM_VERSION} `, "color:white;background:#03a9f4", "color:#03a9f4");
