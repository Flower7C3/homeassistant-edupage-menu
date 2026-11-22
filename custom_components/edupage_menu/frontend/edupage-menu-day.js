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

function guessPickedSensor(hass) {
  return (
    guessEntity(hass, "sensor", "wybrana data") ||
    guessEntity(hass, "sensor", "selected date") ||
    guessEntity(hass, "sensor", "menu picked")
  );
}

function isTodaySensor(entityId, hass) {
  if (!entityId) return false;
  const st = hass.states[entityId];
  if (!st) return false;
  if (st.attributes?.menu_source === "today") return true;
  const id = entityId.toLowerCase();
  if (
    id.includes("menu_today") ||
    id.includes("dzisiaj") ||
    id.includes("dzis")
  ) {
    return true;
  }
  const fn = (st.attributes?.friendly_name || "").toLowerCase();
  return fn.includes("dziś") || fn.includes("dzisiaj") || fn.includes("dzis");
}

function isPickedSensor(entityId, hass) {
  if (!entityId) return false;
  const id = entityId.toLowerCase();
  if (id.includes("menu_day") || id.includes("menu_picked")) return true;
  const fn = (hass.states[entityId]?.attributes?.friendly_name || "").toLowerCase();
  return fn.includes("wybrana") || fn.includes("selected date");
}

function isNextSensor(entityId, hass) {
  if (!entityId) return false;
  const st = hass.states[entityId];
  if (!st) return false;
  if (st.attributes?.menu_source === "next_school_day") return true;
  const id = entityId.toLowerCase();
  if (id.includes("menu_next")) return true;
  const fn = (st.attributes?.friendly_name || "").toLowerCase();
  return fn.includes("następny") || fn.includes("next school");
}

function dateIsoFromSensor(hass, sensorId) {
  if (!sensorId) return null;
  const st = hass.states[sensorId];
  if (!st) return null;

  const raw = st.attributes?.date ?? st.state;
  if (typeof raw === "string" && /^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return raw;
  }

  const title = st.attributes?.title || "";
  const pl = title.match(/(\d{2})\.(\d{2})\.(\d{4})/);
  if (pl) {
    return `${pl[3]}-${pl[2]}-${pl[1]}`;
  }

  return null;
}

function sensorMenuAttrs(hass, sensorId) {
  if (!sensorId) return null;
  const sensorAttrs = hass.states[sensorId]?.attributes || {};
  if (!sensorAttrs.markdown) return null;
  return { markdown: sensorAttrs.markdown };
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
          label: "Pokaż wybór dnia",
          default: true,
          selector: { boolean: {} },
        },
        {
          name: "picker_style",
          label: "Sposób wyboru dnia",
          default: "scroll",
          selector: {
            select: {
              options: [
                { label: "Przewijanie", value: "scroll" },
                { label: "Lista rozwijana", value: "dropdown" },
              ],
            },
          },
        },
        {
          name: "picker_arrows",
          label: "Strzałki poprzedni / następny dzień",
          default: false,
          selector: { boolean: {} },
        },
        {
          name: "picker_today",
          label: "Przycisk „Dziś”",
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
    this._pickerBar = null;
    this._pickerInner = null;
    this._btnPrev = null;
    this._btnNext = null;
    this._btnToday = null;
    this._pickerScroll = null;
    this._pickerSelect = null;
    this._pickerLayoutKey = "";
    this._lastOptionsKey = "";
  }

  setConfig(config) {
    if (!config?.select_entity && !config?.sensor_entity) {
      throw new Error("Podaj encję Wybór dnia (select) lub sensor menu");
    }
    this._config = {
      show_picker: true,
      picker_style: "scroll",
      picker_arrows: false,
      picker_today: true,
      show_title: true,
      append_date: true,
      ...config,
    };
    this._built = false;
    this._pickerBar = null;
    this._pickerInner = null;
    this._btnPrev = null;
    this._btnNext = null;
    this._btnToday = null;
    this._pickerScroll = null;
    this._pickerSelect = null;
    this._pickerLayoutKey = "";
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

  _weekdayPl(iso) {
    if (!iso || typeof iso !== "string") return "";
    const parts = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!parts) return "";
    const day = new Date(
      Number(parts[1]),
      Number(parts[2]) - 1,
      Number(parts[3]),
      12,
      0,
      0
    );
    const labels = ["Ni", "Pon", "Wt", "Śr", "Czw", "Pt", "So"];
    return labels[day.getDay()];
  }

  _menuDateIso() {
    const sensorId = this._config.sensor_entity || this._contentSensorId();
    if (sensorId) {
      const iso = dateIsoFromSensor(this._hass, sensorId);
      if (iso) {
        return iso;
      }
    }

    const selectId = this._config.select_entity;
    if (
      selectId &&
      this._shouldShowPicker() &&
      this._hass.states[selectId]?.attributes?.date
    ) {
      return this._hass.states[selectId].attributes.date;
    }

    return null;
  }

  _contentSensorAttrs() {
    const sensorId = this._config.sensor_entity || this._contentSensorId();
    if (!sensorId) return {};
    return this._hass.states[sensorId]?.attributes || {};
  }

  _resolveCardTitle() {
    if (this._config.show_title === false) {
      return null;
    }

    const base = (this._config.title || "").trim() || "Jadłospis";
    if (this._config.append_date === false) {
      return base;
    }

    const iso = this._menuDateIso();
    const formatted = this._formatMenuDate(iso);
    if (!formatted) {
      return base;
    }

    const sensorAttrs = this._contentSensorAttrs();
    if (sensorAttrs.title_show_weekday) {
      const weekday = this._weekdayPl(iso);
      if (weekday) {
        return `${base} (${weekday}, ${formatted})`;
      }
    }

    return `${base} (${formatted})`;
  }

  _contentSensorId() {
    if (this._config.sensor_entity) {
      return this._config.sensor_entity;
    }
    if (this._config.show_picker) {
      return guessPickedSensor(this._hass);
    }
    return "";
  }

  _shouldShowPicker() {
    if (!this._config.show_picker || !this._config.select_entity) {
      return false;
    }
    const sensorId = this._config.sensor_entity;
    if (!sensorId) {
      return true;
    }
    if (
      isTodaySensor(sensorId, this._hass) ||
      isNextSensor(sensorId, this._hass)
    ) {
      return false;
    }
    return true;
  }

  _menuAttributes() {
    const sensorId = this._config.sensor_entity || this._contentSensorId();
    const fromSensor = sensorMenuAttrs(this._hass, sensorId);
    if (fromSensor) {
      return fromSensor;
    }

    if (this._config.show_picker) {
      return {
        title: "Jadłospis",
        markdown:
          "_Podłącz sensor **Menu — wybrana data**. **Menu — dzisiaj** i **następny dzień** to osobne encje._",
      };
    }

    return {
      title: "Jadłospis",
      markdown: "_Brak jadłospisu. Użyj sensora menu lub włącz wybór dnia._",
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
      ha-card.no-header {
        padding-top: 16px;
      }
      .title {
        font-size: 1.25rem;
        font-weight: var(--ha-font-weight-medium, 500);
        padding: 16px 16px 8px;
      }
      .picker {
        margin: 0 16px 12px;
      }
      .picker-bar {
        display: flex;
        align-items: stretch;
        gap: 8px;
      }
      .picker-inner {
        flex: 1 1 auto;
        min-width: 0;
        display: flex;
        align-items: center;
      }
      .day-nav {
        flex: 0 0 auto;
        align-self: center;
        width: 2.5rem;
        height: 2.5rem;
        padding: 0;
        border-radius: 50%;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        background: var(--card-background-color, var(--ha-card-background, #fff));
        color: var(--primary-text-color, #212121);
        font-size: 1.35rem;
        line-height: 1;
        cursor: pointer;
      }
      .day-nav:hover:not(:disabled) {
        border-color: var(--primary-color);
        color: var(--primary-color);
      }
      .day-nav:disabled {
        opacity: 0.35;
        cursor: default;
      }
      .day-nav:focus-visible {
        outline: 2px solid var(--primary-color);
        outline-offset: 2px;
      }
      .day-today {
        flex: 0 0 auto;
        align-self: center;
        padding: 0 14px;
        height: 2.5rem;
        border-radius: 999px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        background: var(--card-background-color, var(--ha-card-background, #fff));
        color: var(--primary-text-color, #212121);
        font: inherit;
        font-size: 0.9rem;
        font-weight: var(--ha-font-weight-medium, 500);
        cursor: pointer;
      }
      .day-today:hover:not(:disabled) {
        border-color: var(--primary-color);
        color: var(--primary-color);
      }
      .day-today:disabled {
        opacity: 0.35;
        cursor: default;
      }
      .day-today:focus-visible {
        outline: 2px solid var(--primary-color);
        outline-offset: 2px;
      }
      .picker-inner select.day-select {
        width: 100%;
        box-sizing: border-box;
        padding: 10px 12px;
        font-size: 1rem;
        border-radius: 8px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        background: var(--card-background-color, var(--ha-card-background, #fff));
        color: var(--primary-text-color, #212121);
      }
      .day-scroll {
        display: flex;
        gap: 8px;
        overflow-x: auto;
        overflow-y: hidden;
        padding: 4px 2px 8px;
        scroll-snap-type: x proximity;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: thin;
      }
      .day-scroll::-webkit-scrollbar {
        height: 6px;
      }
      .day-chip {
        flex: 0 0 auto;
        scroll-snap-align: start;
        min-width: 4.5rem;
        padding: 8px 10px;
        font: inherit;
        font-size: 0.85rem;
        line-height: 1.25;
        text-align: center;
        border-radius: 12px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        background: var(--card-background-color, var(--ha-card-background, #fff));
        color: var(--primary-text-color, #212121);
        cursor: pointer;
      }
      .day-chip .dow {
        display: block;
        font-weight: var(--ha-font-weight-medium, 500);
      }
      .day-chip .date {
        display: block;
        font-size: 0.75rem;
        opacity: 0.85;
        margin-top: 2px;
      }
      .day-chip[aria-current="true"] {
        border-color: var(--primary-color);
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
      }
      .day-chip[aria-current="true"] .date {
        opacity: 0.92;
      }
      .day-chip:focus-visible {
        outline: 2px solid var(--primary-color);
        outline-offset: 2px;
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
    this._cardEl = card;
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

  _splitDayOption(label) {
    if (!label || typeof label !== "string") {
      return { dow: label || "", date: "" };
    }
    const comma = label.indexOf(", ");
    if (comma === -1) {
      return { dow: label, date: "" };
    }
    return {
      dow: label.slice(0, comma),
      date: label.slice(comma + 2),
    };
  }

  _selectOptionsState() {
    const state = this._hass?.states?.[this._config.select_entity];
    const options = state?.attributes?.options || [];
    const current = state?.state || "";
    return { options, current };
  }

  _selectDayOption(option) {
    if (!option || !this._config.select_entity) return;
    const { current } = this._selectOptionsState();
    if (option === current) return;
    this._hass.callService("select", "select_option", {
      entity_id: this._config.select_entity,
      option,
    });
  }

  _selectRelativeDay(delta) {
    const { options, current } = this._selectOptionsState();
    const idx = options.indexOf(current);
    if (idx < 0) return;
    const next = options[idx + delta];
    if (next) this._selectDayOption(next);
  }

  _optionIso(label) {
    if (typeof label !== "string") return null;
    const m = label.match(/(\d{2})\.(\d{2})\.(\d{4})/);
    if (!m) return null;
    return `${m[3]}-${m[2]}-${m[1]}`;
  }

  _calendarTodayIso() {
    const tz = this._hass?.config?.time_zone;
    try {
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: tz || undefined,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).formatToParts(new Date());
      const pick = (type) => parts.find((p) => p.type === type)?.value || "";
      return `${pick("year")}-${pick("month")}-${pick("day")}`;
    } catch {
      const d = new Date();
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      return `${d.getFullYear()}-${mm}-${dd}`;
    }
  }

  _isSameDayOption(a, b) {
    if (!a || !b) return false;
    if (a === b) return true;
    const ia = this._optionIso(a);
    const ib = this._optionIso(b);
    return Boolean(ia && ib && ia === ib);
  }

  /** Dziś w kalendarzu HA, a gdy brak w liście — najbliższy kolejny dzień z jadłospisem. */
  _todayTargetOption(options) {
    if (!options?.length) return null;
    const todayIso = this._calendarTodayIso();
    const labeled = options
      .map((opt) => ({ opt, iso: this._optionIso(opt) }))
      .filter((entry) => entry.iso);

    const exact = labeled.find((entry) => entry.iso === todayIso);
    if (exact) return exact.opt;

    const onOrAfter = labeled
      .filter((entry) => entry.iso >= todayIso)
      .sort((a, b) => a.iso.localeCompare(b.iso));
    if (onOrAfter.length) return onOrAfter[0].opt;

    return labeled.sort((a, b) => b.iso.localeCompare(a.iso))[0]?.opt || null;
  }

  _selectToday() {
    const { options } = this._selectOptionsState();
    const target = this._todayTargetOption(options);
    if (target) this._selectDayOption(target);
  }

  _updateDayNavButtons(options, current) {
    const idx = options.indexOf(current);
    if (this._btnPrev) {
      this._btnPrev.disabled = idx <= 0;
    }
    if (this._btnNext) {
      this._btnNext.disabled = idx < 0 || idx >= options.length - 1;
    }
    if (this._btnToday) {
      const target = this._todayTargetOption(options);
      this._btnToday.disabled = !target || this._isSameDayOption(current, target);
    }
  }

  _ensurePickerChrome() {
    const useArrows = this._config.picker_arrows === true;
    const useToday = this._config.picker_today === true;
    const style =
      this._config.picker_style === "dropdown" ? "dropdown" : "scroll";
    const layoutKey = `${useArrows}|${useToday}|${style}`;

    if (!this._pickerBar) {
      this._pickerBar = document.createElement("div");
      this._pickerBar.className = "picker-bar";

      this._btnPrev = document.createElement("button");
      this._btnPrev.type = "button";
      this._btnPrev.className = "day-nav day-nav-prev";
      this._btnPrev.setAttribute("aria-label", "Poprzedni dzień");
      this._btnPrev.textContent = "‹";
      this._btnPrev.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._selectRelativeDay(-1);
      });

      this._btnNext = document.createElement("button");
      this._btnNext.type = "button";
      this._btnNext.className = "day-nav day-nav-next";
      this._btnNext.setAttribute("aria-label", "Następny dzień");
      this._btnNext.textContent = "›";
      this._btnNext.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._selectRelativeDay(1);
      });

      this._btnToday = document.createElement("button");
      this._btnToday.type = "button";
      this._btnToday.className = "day-today";
      this._btnToday.textContent = "Dziś";
      this._btnToday.setAttribute("aria-label", "Przejdź do dzisiejszego dnia");
      this._btnToday.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._selectToday();
      });

      this._pickerInner = document.createElement("div");
      this._pickerInner.className = "picker-inner";

      this._pickerSlot.replaceChildren(this._pickerBar);
    }

    if (layoutKey !== this._pickerLayoutKey) {
      this._pickerLayoutKey = layoutKey;
      this._pickerScroll = null;
      this._pickerSelect = null;
      this._lastOptionsKey = "";
      this._pickerBar.replaceChildren();
      if (useArrows) {
        this._pickerBar.appendChild(this._btnPrev);
      }
      this._pickerBar.appendChild(this._pickerInner);
      if (useArrows) {
        this._pickerBar.appendChild(this._btnNext);
      }
      if (useToday) {
        this._pickerBar.appendChild(this._btnToday);
      }
      this._pickerInner.replaceChildren();
    }
  }

  _ensurePickerDropdown(options, current, optionsKey) {
    if (!this._pickerSelect) {
      const selectEl = document.createElement("select");
      selectEl.className = "day-select";
      selectEl.setAttribute("aria-label", "Wybierz dzień");
      selectEl.addEventListener("change", (ev) => {
        const option = ev.target.value;
        if (!option) return;
        ev.stopPropagation();
        this._selectDayOption(option);
      });
      this._pickerInner.replaceChildren(selectEl);
      this._pickerSelect = selectEl;
    }

    if (optionsKey === this._lastOptionsKey) {
      this._updateDayNavButtons(options, current);
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
    this._updateDayNavButtons(options, current);
  }

  _ensurePickerScroll(options, current, optionsKey) {
    if (!this._pickerScroll) {
      const scroll = document.createElement("div");
      scroll.className = "day-scroll";
      scroll.setAttribute("role", "listbox");
      scroll.setAttribute("aria-label", "Wybierz dzień");
      this._pickerInner.replaceChildren(scroll);
      this._pickerScroll = scroll;
    }

    if (optionsKey === this._lastOptionsKey) {
      this._updateDayNavButtons(options, current);
      return;
    }
    this._lastOptionsKey = optionsKey;

    this._pickerScroll.replaceChildren();
    options.forEach((opt) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "day-chip";
      btn.setAttribute("role", "option");
      const { dow, date } = this._splitDayOption(opt);
      if (date) {
        btn.innerHTML = `<span class="dow"></span><span class="date"></span>`;
        btn.querySelector(".dow").textContent = dow;
        btn.querySelector(".date").textContent = date;
      } else {
        btn.textContent = opt;
      }
      if (opt === current) {
        btn.setAttribute("aria-current", "true");
      }
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._selectDayOption(opt);
      });
      this._pickerScroll.appendChild(btn);
    });

    const selected = this._pickerScroll.querySelector('[aria-current="true"]');
    if (selected?.scrollIntoView) {
      selected.scrollIntoView({
        inline: "center",
        block: "nearest",
        behavior: "smooth",
      });
    }
    this._updateDayNavButtons(options, current);
  }

  _ensurePicker() {
    if (!this._shouldShowPicker()) {
      this._pickerSlot.replaceChildren();
      this._pickerBar = null;
      this._pickerInner = null;
      this._btnPrev = null;
      this._btnNext = null;
      this._btnToday = null;
      this._pickerScroll = null;
      this._pickerSelect = null;
      this._pickerLayoutKey = "";
      this._lastOptionsKey = "";
      return;
    }

    const { options, current } = this._selectOptionsState();
    const optionsKey = `${current}|${options.join(";")}|${this._pickerLayoutKey}`;

    this._ensurePickerChrome();

    if (this._config.picker_style === "dropdown") {
      this._ensurePickerDropdown(options, current, optionsKey);
    } else {
      this._ensurePickerScroll(options, current, optionsKey);
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

    const { markdown } = this._menuAttributes();
    const title = this._resolveCardTitle();

    this._hintEl.hidden = true;

    if (title === null) {
      this._titleEl.hidden = true;
      this._titleEl.textContent = "";
      this._cardEl.classList.add("no-header");
    } else {
      this._titleEl.hidden = false;
      this._titleEl.textContent = title;
      this._cardEl.classList.remove("no-header");
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