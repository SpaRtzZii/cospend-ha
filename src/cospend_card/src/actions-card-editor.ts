import { LitElement, html } from "lit";

import { fetchProjects } from "./api";
import { translate } from "./i18n";
import type { CospendActionsCardConfig, HassLike, Project } from "./types";

interface FormSchema {
  name: string;
  selector: Record<string, unknown>;
}

const FLAGS = ["show_add", "show_edit", "show_delete", "allow_write"] as const;

/** Éditeur visuel de la carte d'actions. */
class CospendActionsCardEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _projects: { state: true },
  };

  declare hass?: HassLike;
  declare _config?: CospendActionsCardConfig;
  declare _projects: Project[];

  private _loaded = false;

  constructor() {
    super();
    this._projects = [];
  }

  setConfig(config: CospendActionsCardConfig): void {
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
    return [
      { name: "title", selector: { text: {} } },
      {
        name: "project",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "", label: this._t("editor_project_any") },
              ...this._projects.map((p) => ({
                value: p.id,
                label: p.archived ? `${p.name} (${this._t("archived")})` : p.name,
              })),
            ],
          },
        },
      },
      { name: "show_add", selector: { boolean: {} } },
      { name: "show_edit", selector: { boolean: {} } },
      { name: "show_delete", selector: { boolean: {} } },
      { name: "allow_write", selector: { boolean: {} } },
    ];
  }

  private _data(): Record<string, unknown> {
    const c = this._config;
    return {
      title: c?.title ?? "",
      project: c?.project ?? "",
      show_add: c?.show_add ?? true,
      show_edit: c?.show_edit ?? true,
      show_delete: c?.show_delete ?? true,
      allow_write: c?.allow_write ?? true,
    };
  }

  private _changed(event: CustomEvent<{ value: Record<string, unknown> }>): void {
    event.stopPropagation();
    const value = event.detail.value;
    const config: CospendActionsCardConfig = { ...(this._config as CospendActionsCardConfig) };
    for (const key of ["title", "project"] as const) {
      const text = value[key];
      if (typeof text === "string" && text !== "") config[key] = text;
      else delete config[key];
    }
    const project = this._projects.find((p) => p.id === config.project);
    if (project) config.entry_id = project.entry_id;
    else delete config.entry_id;
    for (const flag of FLAGS) config[flag] = value[flag] !== false;
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

customElements.define("cospend-actions-card-editor", CospendActionsCardEditor);
