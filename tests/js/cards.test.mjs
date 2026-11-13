// Browserless checks of the cards with jsdom. They do not replace a test in a real browser:
// jsdom has no layout, no Home Assistant elements
// (ha-card, ha-icon, ha-form) and no touch input.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { after, test } from "node:test";
import { JSDOM } from "jsdom";

const SOURCE = readFileSync(new URL("../../custom_components/home_modes/frontend/home-modes-cards.js", import.meta.url), "utf8");

const windows = [];
// The cards start an interval timer while attached; closing the window stops it.
after(() => windows.forEach((win) => win.close()));

function boot() {
  const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.eval(SOURCE);
  windows.push(dom.window);
  return dom.window;
}

const MODES = [
  { id: "home", name: "Home", type: "home", icon: "mdi:home" },
  { id: "night", name: "Night", type: "night", icon: "mdi:weather-night" },
];
const OVERLAYS = [{ id: "guest", name: "Guest", type: "guest", icon: "mdi:account-multiple" }];

function makeHass({ allowed, callWS, callService } = {}) {
  const calls = [];
  return {
    calls,
    states: {
      "select.home_mode": {
        state: "Home",
        attributes: {
          mode_id: "home", overlays: [], options: ["Home", "Night"], since: new Date().toISOString(),
          auto: true, override: null, temporary: null,
        },
      },
    },
    callWS: callWS || (async () => allowed || { modes: MODES, overlays: OVERLAYS, can_set_auto: true }),
    callService: callService || (async (domain, service, data) => { calls.push([domain, service, data]); }),
  };
}

async function mount(win, tag, config, hass) {
  const card = win.document.createElement(tag);
  win.document.body.append(card);
  card.setConfig(config);
  card.hass = hass;
  await new Promise((resolve) => setTimeout(resolve, 5));
  return card;
}

// Values created inside the jsdom window have another realm's prototypes.
const plain = (value) => JSON.parse(JSON.stringify(value));
const texts = (card) => [...card.shadowRoot.querySelectorAll("button")].map((b) => b.textContent.trim());

test("both cards and their editors are defined and listed in customCards", () => {
  const win = boot();
  for (const name of ["home-modes-card", "home-modes-guest-card", "home-modes-card-editor", "home-modes-guest-card-editor"]) {
    assert.ok(win.customElements.get(name), name);
  }
  assert.deepEqual(plain(win.customCards.map((c) => c.type).sort()), ["home-modes-card", "home-modes-guest-card"]);
});

test("zero config works: modes, overlay and Auto are shown", async () => {
  const win = boot();
  const card = await mount(win, "home-modes-card", {}, makeHass());
  assert.deepEqual(texts(card), ["Home", "Night", "Guest", "Auto"]);
});

test("role names are never interpreted as HTML", async () => {
  const win = boot();
  const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>';
  const hass = makeHass({ allowed: { modes: [{ id: "home", name: evil, type: "home", icon: "mdi:home" }], overlays: [], can_set_auto: true } });
  const card = await mount(win, "home-modes-card", { title: evil }, hass);
  assert.equal(card.shadowRoot.querySelectorAll("img, script").length, 0);
  assert.ok(texts(card).includes(evil));
  assert.equal(win.__pwned, undefined);
});

test("icons must look like mdi:name; anything else falls back", async () => {
  const win = boot();
  const card = await mount(win, "home-modes-card", { icons: { home: 'javascript:alert(1)', night: "mdi:bed" } }, makeHass());
  const icons = [...card.shadowRoot.querySelectorAll("ha-icon")].map((i) => i.getAttribute("icon"));
  assert.ok(icons.includes("mdi:bed"));
  assert.ok(!icons.some((i) => i.startsWith("javascript")));
});

test("the guest card only shows what the server allows and the config can only narrow it", async () => {
  const win = boot();
  const hass = makeHass({ allowed: { modes: [MODES[1]], overlays: [], can_set_auto: false } });
  const card = await mount(win, "home-modes-guest-card", { roles: ["night", "home", "admin_only"] }, hass);
  assert.deepEqual(texts(card), ["Night"]);
  const narrowed = await mount(win, "home-modes-guest-card", { roles: ["home"] }, hass);
  assert.deepEqual(texts(narrowed), []);
});

test("the guest card never shows Auto or the temporary control, even when configured", async () => {
  const win = boot();
  const card = await mount(win, "home-modes-guest-card", { show_auto: true, show_temporary: true }, makeHass());
  assert.ok(!texts(card).includes("Auto"));
  assert.equal(card.shadowRoot.querySelectorAll("select").length, 0);
});

test("Auto is hidden when the server says the user may not use it", async () => {
  const win = boot();
  const hass = makeHass({ allowed: { modes: MODES, overlays: [], can_set_auto: false } });
  const card = await mount(win, "home-modes-card", {}, hass);
  assert.ok(!texts(card).includes("Auto"));
});

test("buttons call the services with role ids", async () => {
  const win = boot();
  const hass = makeHass();
  const card = await mount(win, "home-modes-card", {}, hass);
  const click = async (label) => {
    [...card.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === label).click();
    await new Promise((resolve) => setTimeout(resolve, 5));
  };
  await click("Night");
  await click("Guest");
  await click("Auto");
  assert.deepEqual(plain(hass.calls), [
    ["home_modes", "set_mode", { mode: "night" }],
    ["home_modes", "set_overlay", { overlay: "guest", active: true }],
    ["home_modes", "set_auto", {}],
  ]);
});

test("a denied action shows the server message", async () => {
  const win = boot();
  const hass = makeHass({ callService: async () => { throw new Error("You are not allowed to change Night."); } });
  const card = await mount(win, "home-modes-card", {}, hass);
  [...card.shadowRoot.querySelectorAll("button")].find((b) => b.textContent.trim() === "Night").click();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(card.shadowRoot.querySelector('[role="alert"]').textContent, "You are not allowed to change Night.");
});

test("a clear message is shown when the integration is not loaded", async () => {
  const win = boot();
  const hass = makeHass({ callWS: async () => { throw { code: "not_found" }; } });
  const card = await mount(win, "home-modes-card", {}, hass);
  assert.match(card.shadowRoot.querySelector('[role="alert"]').textContent, /not loaded/i);
});

test("override and temporary information is shown", async () => {
  const win = boot();
  const hass = makeHass();
  const until = new Date(Date.now() + 25 * 60000).toISOString();
  hass.states["select.home_mode"].attributes.override = { mode: "timed", until };
  hass.states["select.home_mode"].attributes.temporary = { until, revert_to: "home", revert_to_name: "Home" };
  const card = await mount(win, "home-modes-card", {}, hass);
  const text = card.shadowRoot.querySelector(".notes").textContent;
  assert.match(text, /Manual change until/);
  assert.match(text, /Temporary, back to Home/);
});
