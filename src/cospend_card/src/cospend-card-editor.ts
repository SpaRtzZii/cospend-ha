import { LitElement, html } from "lit";

import { fetchProjects } from "./api";
import { translate } from "./i18n";
import type { CospendCardConfig, HassLike, Project } from "./types";

interface FormSchema {
  name: string;
  selector: Record<string, unknown>;
  required?: boolean;
}

/** Éditeur visuel de la carte (affiché dans l'éditeur de tableau de bord de Home Assistant). */
class CospendCardEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _projects: { state: true },
  };

  declare hass?: HassLike;
  declare _config?: CospendCardConfig;
  declare _projects: Project[];

  private _loaded = false;

  constructor() {
    super();
    this._projects = [];
  }

  setConfig(config: CospendCardConfig): void {
    this._config = config;
  }

  protected willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass && !this._loaded) {
      this._loaded = true;
      fetchProjects(this.hass)
        .then((projects) => (this._projects = projects))
        .catch(() => (this._projects = []));
    }
  }

  private _t(key: string): string {
    return translate(this.hass?.locale?.language ?? this.hass?.language, key);
  }

  private _schema(): FormSchema[] {
    const options = [
      { value: "", label: this._t("editor_project_any") },
      ...this._projects.map((project) => ({
        value: project.id,
        label: project.archived ? `${project.name} (${this._t("archived")})` : project.name,
      })),
    ];
    return [
      { name: "title", selector: { text: {} } },
      { name: "project", selector: { select: { mode: "dropdown", options } } },
      { name: "share_url", selector: { text: {} } },
      { name: "show_balances", selector: { boolean: {} } },
      { name: "inline_balances", selector: { boolean: {} } },
      { name: "show_bills", selector: { boolean: {} } },
      { name: "show_search", selector: { boolean: {} } },
      { name: "allow_write", selector: { boolean: {} } },
      { name: "show_settlement", selector: { boolean: {} } },
      { name: "show_project_select", selector: { boolean: {} } },
      { name: "show_stats", selector: { boolean: {} } },
      { name: "wide_layout", selector: { boolean: {} } },
      { name: "allow_manage", selector: { boolean: {} } },
      { name: "page_size", selector: { number: { min: 5, max: 100, step: 5, mode: "box" } } },
    ];
  }

  private _data(): Record<string, unknown> {
    const config = this._config;
    return {
      title: config?.title ?? "",
      project: config?.project ?? "",
      share_url: config?.share_url ?? "",
      show_balances: config?.show_balances ?? true,
      inline_balances: config?.inline_balances ?? false,
      show_bills: config?.show_bills ?? true,
      show_search: config?.show_search ?? true,
      allow_write: config?.allow_write ?? true,
      show_settlement: config?.show_settlement ?? true,
      show_project_select: config?.show_project_select ?? true,
      show_stats: config?.show_stats ?? true,
      wide_layout: config?.wide_layout ?? true,
      allow_manage: config?.allow_manage ?? false,
      page_size: config?.page_size ?? 20,
    };
  }

  private _changed(event: CustomEvent<{ value: Record<string, unknown> }>): void {
    event.stopPropagation();
    const value = event.detail.value;
    const config: CospendCardConfig = { ...(this._config as CospendCardConfig) };
    for (const key of ["title", "project", "share_url"] as const) {
      const text = value[key];
      if (typeof text === "string" && text !== "") config[key] = text;
      else delete config[key];
    }
    // L'identifiant d'entrée n'a de sens qu'avec un projet choisi ; il se retrouve par le projet.
    const project = this._projects.find((item) => item.id === config.project);
    if (project) config.entry_id = project.entry_id;
    else delete config.entry_id;
    for (const key of ["show_balances", "inline_balances", "show_bills", "show_search", "allow_write", "show_settlement", "show_stats", "show_project_select", "wide_layout", "allow_manage"] as const) {
      config[key] = value[key] !== false;
    }
    config.page_size = Number(value.page_size) || 20;
    this._config = config;
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }),
    );
  }

  protected render() {
    if (!this._config) return html``;
    return html`
      <ha-form
        .hass=${this.hass}
        .data=${this._data()}
        .schema=${this._schema()}
        .computeLabel=${(schema: FormSchema) => this._t(`editor_${schema.name}`)}
        @value-changed=${this._changed}
      ></ha-form>
    `;
  }
}

customElements.define("cospend-card-editor", CospendCardEditor);
