/**
 * Lovelace card: EduPage school lunch menu with day picker.
 */

function guessEntity(hass, domain, namePart) {
  const needle = namePart.toLowerCase();
  return (
    Object.keys(hass.states).find((id) => {
      if (!id.startsWith(`${domain}.`)) return false;
      const label = (
        hass.states[id].attributes?.friendly_name || id
      ).toLowerCase();
      return label.includes(needle);
    }) || ""
  );
}

function fireEvent(node, type, detail) {
  node.dispatchEvent(
    new CustomEvent(type, { detail, bubbles: true, composed: true })
  );
}

function isTodaySensor(entityId, hass) {
  if (!entityId) return false;
  const id = entityId.toLowerCase();
  if (id.includes("menu_today") || id.includes("_dzi")) return true;
  const fn = (hass.states[entityId]?.attributes?.friendly_name || "").toLowerCase();
  return fn.includes("dziś") || fn.includes("dzis");
}

class EdupageMenuDayCard extends HTMLElement {
  static getStubConfig(hass) {
    return {
      type: "custom:edupage-menu-day",
      select_entity:
        guessEntity(hass, "select", "wybór dnia") ||
        guessEntity(hass, "select", "day picker"),
      sensor_entity:
        guessEntity(hass, "sensor", "wybrana data") ||
        guessEntity(hass, "sensor", "selected date"),
      show_picker: true,
    };
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "select_entity",
          required: true,
          selector: { entity: { domain: "select" } },
        },
        {
          name: "sensor_entity",
          required: false,
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "show_picker",
          default: true,
          selector: { boolean: {} },
        },
        {
          name: "title",
          required: false,
          selector: { text: {} },
        },
        {
          name: "show_title",
          default: true,
          selector: { boolean: {} },
        },
        {
          name: "append_date",
          default: true,
          selector: { boolean: {} },
        },
      ],
    };
  }

  constructor() {
    super();
    this._built = false;
    this._pickerSelect = null;
    this._lastOptionsKey = "";
  }

  setConfig(config) {
    if (!config?.select_entity && !config?.sensor_entity) {
      throw new Error("Podaj encję Wybór dnia (select) lub sensor menu");
    }
    this._config = {
      show_picker: true,
      show_title: true,
      append_date: true,
      ...config,
    };
    this._built = false;
    this._pickerSelect = null;
    this._lastOptionsKey = "";
    this._updateContent();
  }

  set hass(hass) {
    this._hass = hass;
    this._updateContent();
  }

  getCardSize() {
    return 4;
  }

  _formatMenuDate(iso) {
    if (!iso || typeof iso !== "string") return "";
    const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return "";
    return `${match[3]}.${match[2]}.${match[1]}`;
  }

  _menuDateIso() {
    const selectId = this._config.select_entity;
    const sensorId = this._config.sensor_entity;
    return (
      (selectId && this._hass.states[selectId]?.attributes?.date) ||
      (sensorId && this._hass.states[sensorId]?.attributes?.date) ||
      null
    );
  }

  _resolveCardTitle(entityTitle) {
    if (this._config.show_title === false) {
      return null;
    }

    const custom = (this._config.title || "").trim();
    if (custom) {
      if (this._config.append_date !== false) {
        const formatted = this._formatMenuDate(this._menuDateIso());
        if (formatted) {
          return `${custom} (${formatted})`;
        }
      }
      return custom;
    }

    return entityTitle;
  }

  _menuAttributes() {
    const selectId = this._config.select_entity;
    const selectAttrs = selectId
      ? this._hass.states[selectId]?.attributes
      : null;

    if (
      this._config.show_picker &&
      selectId &&
      selectAttrs?.markdown
    ) {
      return {
        title: selectAttrs.title || "Jadłospis",
        markdown: selectAttrs.markdown,
      };
    }

    const sensorId = this._config.sensor_entity;
    if (sensorId) {
      const sensorAttrs = this._hass.states[sensorId]?.attributes || {};
      if (sensorAttrs.markdown) {
        return {
          title: sensorAttrs.title || "Jadłospis",
          markdown: sensorAttrs.markdown,
        };
      }
    }

    if (selectAttrs?.markdown) {
      return {
        title: selectAttrs.title || "Jadłospis",
        markdown: selectAttrs.markdown,
      };
    }

    return {
      title: "Jadłospis",
      markdown: "_Brak jadłospisu. Sprawdź integrację lub wybierz dzień._",
    };
  }

  _ensureDom() {
    if (this._built) return;

    while (this.firstChild) {
      this.removeChild(this.firstChild);
    }

    const style = document.createElement("style");
    style.textContent = `
      ha-card {
        padding: 0 0 16px;
        display: block;
      }
      .title {
        font-size: 1.25rem;
        font-weight: var(--ha-font-weight-medium, 500);
        padding: 16px 16px 8px;
      }
      .picker {
        margin: 0 16px 12px;
      }
      .picker select.day-select {
        width: 100%;
        box-sizing: border-box;
        padding: 10px 12px;
        font-size: 1rem;
        border-radius: 8px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        background: var(--card-background-color, var(--ha-card-background, #fff));
        color: var(--primary-text-color, #212121);
      }
      .menu {
        padding: 0 16px;
      }
      .hint {
        margin: 0 16px 12px;
        padding: 8px 12px;
        border-radius: 8px;
        background: var(--warning-color, #fff3cd);
        color: var(--primary-text-color, #212121);
        font-size: 0.85rem;
      }
    `;
    this.appendChild(style);

    const card = document.createElement("ha-card");
    this._titleEl = document.createElement("div");
    this._titleEl.className = "title";
    card.appendChild(this._titleEl);

    this._hintEl = document.createElement("div");
    this._hintEl.className = "hint";
    this._hintEl.hidden = true;
    card.appendChild(this._hintEl);

    this._pickerSlot = document.createElement("div");
    this._pickerSlot.className = "picker";
    card.appendChild(this._pickerSlot);

    this._menuSlot = document.createElement("div");
    this._menuSlot.className = "menu";
    card.appendChild(this._menuSlot);

    this.appendChild(card);
    this._built = true;
  }

  _ensurePicker() {
    const show = this._config.show_picker && this._config.select_entity;
    if (!show) {
      this._pickerSlot.replaceChildren();
      this._pickerSelect = null;
      this._lastOptionsKey = "";
      return;
    }

    const state = this._hass.states[this._config.select_entity];
    const options = state?.attributes?.options || [];
    const current = state?.state || "";
    const optionsKey = `${current}|${options.join(";")}`;

    if (!this._pickerSelect) {
      const selectEl = document.createElement("select");
      selectEl.className = "day-select";
      selectEl.setAttribute("aria-label", "Wybierz dzień");
      selectEl.addEventListener("change", (ev) => {
        const option = ev.target.value;
        if (!option) return;
        ev.stopPropagation();
        this._hass.callService("select", "select_option", {
          entity_id: this._config.select_entity,
          option,
        });
      });
      this._pickerSlot.replaceChildren(selectEl);
      this._pickerSelect = selectEl;
    }

    if (optionsKey === this._lastOptionsKey) {
      return;
    }
    this._lastOptionsKey = optionsKey;

    this._pickerSelect.innerHTML = "";
    options.forEach((opt) => {
      const item = document.createElement("option");
      item.value = opt;
      item.textContent = opt;
      if (opt === current) item.selected = true;
      this._pickerSelect.appendChild(item);
    });
    if (current) {
      this._pickerSelect.value = current;
    }
  }

  _ensureMarkdown() {
    if (!this._markdownEl) {
      this._markdownEl = document.createElement("ha-markdown");
      this._menuSlot.replaceChildren(this._markdownEl);
    }
    this._markdownEl.hass = this._hass;
  }

  _updateContent() {
    if (!this._hass || !this._config) return;

    this._ensureDom();
    this._ensurePicker();
    this._ensureMarkdown();

    const { title: entityTitle, markdown } = this._menuAttributes();
    const title = this._resolveCardTitle(entityTitle);

    const wrongSensor =
      this._config.show_picker &&
      this._config.sensor_entity &&
      isTodaySensor(this._config.sensor_entity, this._hass) &&
      this._config.select_entity &&
      !this._hass.states[this._config.select_entity]?.attributes?.markdown;

    if (wrongSensor) {
      this._hintEl.hidden = false;
      this._hintEl.textContent =
        "Podłączono „Menu — dziś”. Przy wyborze dnia treść bierze się z encji „Wybór dnia” (usuń złý sensor z karty lub użyj „Menu — wybrana data”).";
    } else {
      this._hintEl.hidden = true;
    }

    if (title === null) {
      this._titleEl.hidden = true;
      this._titleEl.textContent = "";
    } else {
      this._titleEl.hidden = false;
      this._titleEl.textContent = title;
    }
    this._markdownEl.content = markdown;
  }
}

customElements.define("edupage-menu-day", EdupageMenuDayCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "edupage-menu-day",
  name: "Jadłospis dnia",
  description: "EduPage: wybór dnia i lista dań",
  preview: false,
  documentationURL:
    "https://github.com/EdupageAPI/edupage-api/blob/master/edupage_api/lunches.py",
});