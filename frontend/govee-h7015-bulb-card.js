/**
 * Govee H7015 Bulb Editor — custom Lovelace card.
 *
 * Features:
 * - 15 color swatches (one per bulb), click to select + color picker
 * - 12 preset patterns: Rainbow, Warm White, Fireplace, Ocean, Christmas,
 *   Sunset, USA Flag, Candy Cane, All Red/Green/Blue, All Off
 * - "Save as Scene" button — snapshots current bulb colors as a HA scene
 * - Power toggle
 *
 * Installation:
 *   1. Copy this file to /config/www/govee-h7015-bulb-card.js
 *   2. Add to Lovelace resources: Settings → Dashboards → Resources → Add
 *      URL: /local/govee-h7015-bulb-card.js
 *      Type: JavaScript Module
 *   3. Add card to dashboard via "Manual" card type:
 *      type: custom:govee-h7015-bulb-card
 *      entity: light.patio_lights      # main light entity
 *      device_id: <your H7015 device ID>
 *
 * Or install via HACS as a frontend module.
 */

// Preset color patterns. Each is a function returning an array of 15 [r,g,b] tuples.
const PRESETS = {
  rainbow: {
    name: "🌈 Rainbow",
    colors: () => {
      const out = [];
      for (let i = 0; i < 15; i++) {
        const hue = (i * 360) / 15;
        out.push(hslToRgb(hue / 360, 1, 0.5));
      }
      return out;
    },
  },
  warm: {
    name: "💡 Warm White",
    colors: () => Array(15).fill([255, 196, 120]),
  },
  fireplace: {
    name: "🔥 Fireplace",
    colors: () => {
      // Warm flickering reds, oranges, and yellows
      const base = [
        [255, 60, 0],    // deep red
        [255, 100, 0],   // red-orange
        [255, 140, 0],   // orange
        [255, 180, 20],  // amber
        [255, 120, 10],  // orange-red
        [255, 80, 0],    // red
        [255, 160, 30],  // amber
        [255, 200, 50],  // yellow-orange
        [255, 90, 0],    // red-orange
        [255, 130, 5],   // orange
        [255, 170, 20],  // amber
        [255, 50, 0],    // deep red
        [255, 110, 0],   // orange-red
        [255, 150, 10],  // orange
        [255, 190, 40],  // amber
      ];
      return base;
    },
  },
  ocean: {
    name: "🌊 Ocean",
    colors: () => {
      // Blues and cyans flowing like waves
      const out = [];
      for (let i = 0; i < 15; i++) {
        const t = i / 14;
        // Interpolate between deep blue and cyan
        const r = Math.round(0 + t * 0);
        const g = Math.round(100 + t * 155);
        const b = Math.round(200 + t * 55);
        out.push([r, g, b]);
      }
      return out;
    },
  },
  christmas: {
    name: "🎄 Christmas",
    colors: () => {
      // Alternating red, green, gold
      const pattern = [
        [255, 0, 0],     // red
        [0, 180, 0],     // green
        [255, 215, 0],   // gold
        [0, 180, 0],     // green
        [255, 0, 0],     // red
        [255, 215, 0],   // gold
        [0, 180, 0],     // green
        [255, 0, 0],     // red
        [255, 215, 0],   // gold
        [0, 180, 0],     // green
        [255, 0, 0],     // red
        [255, 215, 0],   // gold
        [0, 180, 0],     // green
        [255, 0, 0],     // red
        [255, 215, 0],   // gold
      ];
      return pattern;
    },
  },
  sunset: {
    name: "🌅 Sunset",
    colors: () => {
      // Gradient from deep red to orange to yellow to pink
      const stops = [
        [180, 30, 80],   // deep magenta-red
        [220, 50, 60],   // red
        [255, 80, 40],   // red-orange
        [255, 120, 30],  // orange
        [255, 160, 40],  // amber
        [255, 200, 60],  // yellow-orange
        [255, 220, 100], // yellow
        [255, 200, 60],  // yellow-orange
        [255, 160, 40],  // amber
        [255, 120, 30],  // orange
        [255, 80, 40],   // red-orange
        [220, 50, 60],   // red
        [180, 30, 80],   // deep magenta-red
        [150, 20, 100],  // magenta
        [120, 10, 120],  // purple
      ];
      return stops;
    },
  },
  flag: {
    name: "🇺🇸 Flag",
    colors: () => {
      // Red, white, blue pattern
      const pattern = [
        [255, 0, 0],     // red
        [255, 255, 255], // white
        [0, 0, 180],     // blue
        [255, 0, 0],     // red
        [255, 255, 255], // white
        [0, 0, 180],     // blue
        [255, 0, 0],     // red
        [255, 255, 255], // white
        [0, 0, 180],     // blue
        [255, 0, 0],     // red
        [255, 255, 255], // white
        [0, 0, 180],     // blue
        [255, 0, 0],     // red
        [255, 255, 255], // white
        [0, 0, 180],     // blue
      ];
      return pattern;
    },
  },
  candyCane: {
    name: "🍭 Candy Cane",
    colors: () => {
      // Alternating red and white
      const pattern = [];
      for (let i = 0; i < 15; i++) {
        if (i % 2 === 0) {
          pattern.push([255, 255, 255]); // white
        } else {
          pattern.push([255, 30, 30]);   // red
        }
      }
      return pattern;
    },
  },
  red: {
    name: "🔴 All Red",
    colors: () => Array(15).fill([255, 0, 0]),
  },
  green: {
    name: "🟢 All Green",
    colors: () => Array(15).fill([0, 255, 0]),
  },
  blue: {
    name: "🔵 All Blue",
    colors: () => Array(15).fill([0, 0, 255]),
  },
  off: {
    name: "⚫ All Off",
    colors: () => Array(15).fill([0, 0, 0]),
  },
};

// Color utility functions (module-level)
function hslToRgb(h, s, l) {
  let r, g, b;
  if (s === 0) {
    r = g = b = l;
  } else {
    const hue2rgb = (p, q, t) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1 / 3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1 / 3);
  }
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

function rgbToHex(rgb) {
  const toHex = (n) => n.toString(16).padStart(2, "0");
  return `#${toHex(rgb[0])}${toHex(rgb[1])}${toHex(rgb[2])}`;
}

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b];
}

// Entity friendly_name (and by extension entity_id) isn't trusted input —
// it can come from a device's advertised BLE name at discovery time, or
// from anyone with entity-rename access. Escape before interpolating into
// innerHTML so it can't inject markup/script into the dashboard.
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}


class GoveeH7015BulbCard extends HTMLElement {
  static get properties() {
    return {
      hass: {},
      config: {},
    };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.bulbColors = {};
    this.selectedBulb = null;
    this.sceneName = "";
    this.showSceneDialog = false;
  }

  set hass(hass) {
    this._hass = hass;
    this.render();
  }

  get hass() {
    return this._hass;
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("entity is required (the main H7015 light entity)");
    }
    if (!config.device_id) {
      throw new Error("device_id is required (find it in Settings → Devices)");
    }
    this.config = config;
  }

  getCardSize() {
    return 5;
  }

  render() {
    if (!this._hass || !this.config) return;

    const entityId = this.config.entity;
    const deviceId = this.config.device_id;
    const stateObj = this._hass.states[entityId];

    if (!stateObj) {
      this.shadowRoot.innerHTML = `<div style="padding:16px;color:var(--error-color)">Entity ${escapeHtml(entityId)} not found</div>`;
      return;
    }

    // Read per-bulb entities to get current colors
    const baseEntityId = entityId.replace("light.", "");
    const bulbColors = {};
    for (let i = 0; i < 15; i++) {
      // Bulb entities are 1-indexed in entity_id (Bulb 1 → bulb_1)
      const bulbEntityId = `light.${baseEntityId}_bulb_${i + 1}`;
      const bulbState = this._hass.states[bulbEntityId];
      if (bulbState && bulbState.attributes.rgb_color) {
        bulbColors[i] = bulbState.attributes.rgb_color;
      } else {
        bulbColors[i] = [60, 60, 60]; // dark gray = unknown/off
      }
    }
    this.bulbColors = bulbColors;

    const isOn = stateObj.state === "on";

    // Build preset buttons HTML
    const presetButtons = Object.entries(PRESETS).map(([key, preset]) =>
      `<div class="preset-btn" data-preset="${key}">${preset.name}</div>`
    ).join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 16px;
          font-family: var(--paper-font-body1_-_font-family);
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .header h3 {
          margin: 0;
          font-size: 1.2em;
        }
        .header-actions {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .power-toggle {
          cursor: pointer;
          padding: 8px 16px;
          border-radius: 20px;
          background: ${isOn ? "var(--primary-color)" : "var(--secondary-background-color)"};
          color: ${isOn ? "white" : "var(--primary-text-color)"};
          font-weight: 500;
        }
        .save-scene-btn {
          cursor: pointer;
          padding: 8px 16px;
          border-radius: 20px;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          font-weight: 500;
          border: 1px solid var(--divider-color);
        }
        .save-scene-btn:hover {
          background: var(--primary-color);
          color: white;
        }
        .bulbs {
          display: grid;
          grid-template-columns: repeat(5, 1fr);
          gap: 12px;
          margin-bottom: 16px;
        }
        .bulb {
          aspect-ratio: 1;
          border-radius: 50%;
          cursor: pointer;
          border: 3px solid var(--card-background-color);
          box-shadow: 0 2px 4px rgba(0,0,0,0.2);
          transition: transform 0.1s, box-shadow 0.1s;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 0.7em;
          color: rgba(255,255,255,0.8);
          text-shadow: 0 1px 2px rgba(0,0,0,0.8);
        }
        .bulb:hover {
          transform: scale(1.1);
          box-shadow: 0 4px 8px rgba(0,0,0,0.3);
        }
        .bulb.selected {
          border-color: var(--primary-color);
          border-width: 4px;
        }
        .color-picker {
          display: ${this.selectedBulb !== null ? "block" : "none"};
          margin-bottom: 16px;
          padding: 12px;
          background: var(--secondary-background-color);
          border-radius: 8px;
        }
        .color-picker label {
          display: block;
          margin-bottom: 8px;
          font-weight: 500;
        }
        .color-picker input[type="color"] {
          width: 100%;
          height: 40px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
        }
        .presets {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-bottom: 16px;
        }
        .preset-btn {
          padding: 8px 12px;
          border-radius: 16px;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
          cursor: pointer;
          font-size: 0.85em;
          border: 1px solid var(--divider-color);
        }
        .preset-btn:hover {
          background: var(--primary-color);
          color: white;
        }
        .scene-dialog {
          display: ${this.showSceneDialog ? "block" : "none"};
          position: fixed;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          background: var(--card-background-color);
          padding: 24px;
          border-radius: 12px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.3);
          z-index: 999;
          min-width: 350px;
        }
        .scene-dialog h4 {
          margin: 0 0 16px 0;
        }
        .scene-dialog input[type="text"] {
          width: 100%;
          padding: 8px 12px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          margin-bottom: 16px;
          font-size: 1em;
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        .scene-dialog .buttons {
          display: flex;
          gap: 8px;
          justify-content: flex-end;
        }
        .scene-dialog .btn {
          padding: 8px 16px;
          border-radius: 4px;
          cursor: pointer;
          font-weight: 500;
          border: none;
        }
        .scene-dialog .btn-cancel {
          background: var(--secondary-background-color);
          color: var(--primary-text-color);
        }
        .scene-dialog .btn-save {
          background: var(--primary-color);
          color: white;
        }
        .scene-overlay {
          display: ${this.showSceneDialog ? "block" : "none"};
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          background: rgba(0,0,0,0.5);
          z-index: 998;
        }
        .instructions {
          font-size: 0.8em;
          color: var(--secondary-text-color);
          margin-top: 12px;
        }
        .status-msg {
          font-size: 0.85em;
          color: var(--secondary-text-color);
          margin-top: 8px;
          min-height: 1.2em;
        }
      </style>
      <div class="header">
        <h3>${escapeHtml(stateObj.attributes.friendly_name || entityId)}</h3>
        <div class="header-actions">
          <div class="save-scene-btn" id="save-scene-btn">💾 Save as Scene</div>
          <div class="power-toggle" id="power-toggle">${isOn ? "ON" : "OFF"}</div>
        </div>
      </div>
      <div class="bulbs" id="bulbs">
        ${Object.entries(bulbColors).map(([i, rgb]) => `
          <div class="bulb ${this.selectedBulb === parseInt(i) ? "selected" : ""}"
               data-bulb="${i}"
               style="background: rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})">
            ${parseInt(i) + 1}
          </div>
        `).join("")}
      </div>
      <div class="color-picker" id="color-picker">
        <label>Bulb ${this.selectedBulb !== null ? this.selectedBulb + 1 : ""} Color</label>
        <input type="color" id="color-input"
               value="${this.selectedBulb !== null ? rgbToHex(bulbColors[this.selectedBulb]) : "#808080"}">
      </div>
      <div class="presets" id="presets">
        ${presetButtons}
      </div>
      <div class="status-msg" id="status-msg"></div>
      <div class="instructions">
        Click a bulb to select it, then use the color picker to change its color.
        Use presets to set all bulbs at once. Click "Save as Scene" to snapshot
        the current bulb colors as a HA scene you can recall later.
      </div>
      <div class="scene-overlay" id="scene-overlay"></div>
      <div class="scene-dialog" id="scene-dialog">
        <h4>💾 Save Current Colors as Scene</h4>
        <input type="text" id="scene-name-input" placeholder="Scene name (e.g. Christmas)"
               value="${escapeHtml(this.sceneName)}">
        <div class="buttons">
          <div class="btn btn-cancel" id="scene-cancel">Cancel</div>
          <div class="btn btn-save" id="scene-save">Save Scene</div>
        </div>
      </div>
    `;

    this.attachListeners(deviceId, entityId);
  }

  attachListeners(deviceId, entityId) {
    // Power toggle
    this.shadowRoot.querySelector("#power-toggle").addEventListener("click", () => {
      this._hass.callService("light", "toggle", { entity_id: entityId });
    });

    // Bulb selection
    this.shadowRoot.querySelectorAll(".bulb").forEach((bulb) => {
      bulb.addEventListener("click", () => {
        this.selectedBulb = parseInt(bulb.dataset.bulb);
        this.render();
      });
    });

    // Color picker
    const colorInput = this.shadowRoot.querySelector("#color-input");
    if (colorInput) {
      colorInput.addEventListener("change", (e) => {
        if (this.selectedBulb === null) return;
        const rgb = hexToRgb(e.target.value);
        this.callSetBulb(deviceId, this.selectedBulb, rgb);
      });
    }

    // Presets
    this.shadowRoot.querySelectorAll(".preset-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const presetKey = btn.dataset.preset;
        this.applyPreset(deviceId, presetKey);
      });
    });

    // Save as Scene
    this.shadowRoot.querySelector("#save-scene-btn").addEventListener("click", () => {
      this.showSceneDialog = true;
      this.render();
      // Focus the input
      setTimeout(() => {
        const input = this.shadowRoot.querySelector("#scene-name-input");
        if (input) input.focus();
      }, 50);
    });

    // Scene dialog buttons
    const cancelBtn = this.shadowRoot.querySelector("#scene-cancel");
    const saveBtn = this.shadowRoot.querySelector("#scene-save");
    const overlay = this.shadowRoot.querySelector("#scene-overlay");
    const nameInput = this.shadowRoot.querySelector("#scene-name-input");

    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => {
        this.showSceneDialog = false;
        this.render();
      });
    }
    if (overlay) {
      overlay.addEventListener("click", () => {
        this.showSceneDialog = false;
        this.render();
      });
    }
    if (saveBtn) {
      saveBtn.addEventListener("click", () => {
        this.saveAsScene(deviceId, entityId);
      });
    }
    if (nameInput) {
      nameInput.addEventListener("input", (e) => {
        this.sceneName = e.target.value;
      });
      nameInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          this.saveAsScene(deviceId, entityId);
        }
      });
    }
  }

  callSetBulb(deviceId, bulb, rgb) {
    // Store old color for rollback on error
    const oldColor = this.bulbColors[bulb] ? [...this.bulbColors[bulb]] : null;

    // Optimistic UI update
    this.bulbColors[bulb] = rgb;
    const bulbEl = this.shadowRoot.querySelector(`.bulb[data-bulb="${bulb}"]`);
    if (bulbEl) {
      bulbEl.style.background = `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
    }

    // Fire and forget — but revert on error
    this._hass.callService("govee_h7015_ble", "set_bulb", {
      bulb: bulb,
      rgb: rgb,
      device_id: [deviceId],
    }).catch((err) => {
      // Revert optimistic update on failure
      if (oldColor) {
        this.bulbColors[bulb] = oldColor;
      } else {
        delete this.bulbColors[bulb];
      }
      if (bulbEl) {
        const c = oldColor || [60, 60, 60];
        bulbEl.style.background = `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
      }
      this.showStatus(`✗ Failed to set bulb ${bulb + 1}: ${err.message || err}`);
    });
  }

  applyPreset(deviceId, presetKey) {
    const preset = PRESETS[presetKey];
    if (!preset) return;

    // Disable preset buttons during application to prevent overlap
    this._applyingPreset = true;
    this.shadowRoot.querySelectorAll(".preset-btn").forEach((btn) => {
      btn.style.opacity = "0.5";
      btn.style.pointerEvents = "none";
    });

    this.showStatus(`Applying ${preset.name}...`);

    const colors = preset.colors();
    for (let i = 0; i < 15; i++) {
      setTimeout(() => {
        this.callSetBulb(deviceId, i, colors[i]);
        if (i === 14) {
          setTimeout(() => {
            this.showStatus(`${preset.name} applied ✓`);
            this._applyingPreset = false;
            this.render(); // full re-render after preset completes
          }, 150);
        }
      }, i * 80);
    }
  }

  async saveAsScene(deviceId, entityId) {
    const name = this.sceneName.trim();
    if (!name) {
      this.showStatus("⚠️ Please enter a scene name");
      return;
    }

    this.showStatus(`Saving "${name}"...`);

    // Use the integration's snapshot_scene service, which handles entity ID
    // lookup via the entity registry (the card can't reliably guess entity IDs
    // because HA generates them from the device name, not the unique_id).
    try {
      await this._hass.callService("govee_h7015_ble", "snapshot_scene", {
        scene_name: name,
        device_id: [deviceId],
      });

      this.showStatus(`✓ Scene "${name}" saved! Find it in Settings → Scenes`);
      this.showSceneDialog = false;
      this.sceneName = "";
      this.render();
    } catch (err) {
      this.showStatus(`✗ Failed to save scene: ${err.message || err}`);
    }
  }

  showStatus(msg) {
    const el = this.shadowRoot.querySelector("#status-msg");
    if (el) {
      el.textContent = msg;
    }
  }
}

// Register the card
customElements.define("govee-h7015-bulb-card", GoveeH7015BulbCard);

// Register card metadata for the card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "govee-h7015-bulb-card",
  name: "Govee H7015 Bulb Editor",
  description: "Visual editor for individual bulb colors on the Govee H7015 string light",
  preview: false,
});
