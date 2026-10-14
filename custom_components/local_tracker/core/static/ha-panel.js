// Home Assistant sidebar panel for LoCal.
// Shows the LoCal app in a same-origin frame and hands it the `hass` object, so the app can talk to
// the LoCal integration over Home Assistant's websocket (as the signed-in HA user) and use the
// Home Assistant phone app's barcode scanner.
const VERSION = new URL(import.meta.url).searchParams.get("v") || "";

class LoCalPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        /* Home Assistant doesn't give panels a fixed height, so fill the viewport ourselves. */
        :host { display: block; position: relative; height: 100vh; height: 100dvh; overflow: hidden;
                background: var(--primary-background-color); }
        .bar {
          display: none; align-items: center; gap: 4px; box-sizing: border-box;
          position: absolute; top: 0; left: 0; right: 0;
          padding: env(safe-area-inset-top) 4px 0;
          height: calc(var(--header-height, 56px) + env(safe-area-inset-top));
          background: var(--app-header-background-color, var(--primary-color, #03a9f4));
          color: var(--app-header-text-color, var(--text-primary-color, #fff));
          font: 400 20px/1 var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
          border-bottom: var(--app-header-border-bottom, none);
        }
        :host([narrow]) .bar { display: flex; }
        button {
          background: none; border: 0; color: inherit; width: 48px; height: 48px; border-radius: 50%;
          display: grid; place-items: center; cursor: pointer;
        }
        button:focus-visible { outline: 2px solid currentColor; }
        iframe {
          position: absolute; left: 0; right: 0; bottom: 0; top: 0;
          width: 100%; height: 100%; border: 0; display: block; background: transparent;
        }
        :host([narrow]) iframe {
          top: calc(var(--header-height, 56px) + env(safe-area-inset-top));
          height: calc(100% - var(--header-height, 56px) - env(safe-area-inset-top));
        }
      </style>
      <div class="bar">
        <button aria-label="Open the Home Assistant menu">
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path fill="currentColor" d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"/></svg>
        </button>
        <span>LoCal</span>
      </div>
      <iframe title="LoCal" allow="camera; clipboard-write"></iframe>`;
    this._frame = this.shadowRoot.querySelector("iframe");
    this.shadowRoot.querySelector("button").addEventListener("click", () =>
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true })));
    this._frame.addEventListener("load", () => this._push());
    this._frame.src = `/local_tracker_static/ha.html?ha=1&v=${encodeURIComponent(VERSION)}`;
  }

  set hass(hass) {
    this._hass = hass;
    this._push();
  }

  set narrow(narrow) {
    this.toggleAttribute("narrow", !!narrow);
  }

  set panel(panel) {
    this._panel = panel;
  }

  _push() {
    const win = this._frame?.contentWindow;
    if (this._hass && win && typeof win.__localTrackerSetHass === "function") win.__localTrackerSetHass(this._hass);
  }
}

if (!customElements.get("local-tracker-panel")) customElements.define("local-tracker-panel", LoCalPanel);
