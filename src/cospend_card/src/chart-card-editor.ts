import { LitElement, html } from "lit";

import { fetchProjects } from "./api";
import { translate } from "./i18n";
import type { ChartKind, ChartPeriod, CospendChartCardConfig, HassLike, Project } from "./types";

interface FormSchema {
  name: string;
  selector: Record<string, unknown>;
}

const KINDS: ChartKind[] = ["months", "categories", "members", "flows", "balances"];
const PERIODS: ChartPeriod[] = ["month", "last_month", "last_30", "year", "all"];

/** Éditeur visuel de la carte graphique. */
class CospendChartCardEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _projects: { state: true },
  };

  declare hass?: HassLike;
  declare _config?: CospendChartCardConfig;
  declare _projects: Project[];

  private _loaded = false;

  constructor() {
    super();
    this._projects = [];
  }

  setConfig(config: CospendChartCardConfig): void {
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

  /** Projet dont on propose les membres et les catégories : celui choisi, sinon le premier. */
  private _current(): Project | undefined {
    const wanted = this._config?.project;
    return wanted
      ? this._projects.find((p) => p.id === wanted)
      : this._projects.find((p) => !p.archived);
  }

  private _schema(): FormSchema[] {
    const project = this._current();
    const select = (options: Array<{ value: string; label: string }>) => ({
      select: { mode: "dropdown", options },
    });
    return [
      { name: "title", selector: { text: {} } },
      {
        name: "project",
        selector: select([
          { value: "", label: this._t("editor_project_any") },
          ...this._projects.map((p) => ({
            value: p.id,
            label: p.archived ? `${p.name} (${this._t("archived")})` : p.name,
          })),
        ]),
      },
      {
        name: "chart",
        selector: select(KINDS.map((k) => ({ value: k, label: this._t(`chart_${k}`) }))),
      },
      {
        name: "period",
        selector: select(PERIODS.map((p) => ({ value: p, label: this._t(`period_${p}`) }))),
      },
      {
        name: "payer",
        selector: select([
          { value: "", label: this._t("stats_any") },
          ...(project?.members ?? []).map((m) => ({ value: String(m.id), label: m.name })),
        ]),
      },
      {
        name: "category",
        selector: select([
          { value: "", label: this._t("stats_any") },
          { value: "0", label: this._t("no_category") },
          ...(project?.categories ?? []).map((c) => ({
            value: String(c.id),
            label: `${c.icon} ${c.name}`.trim(),
          })),
        ]),
      },
      { name: "include_reimbursements", selector: { boolean: {} } },
      { name: "show_total", selector: { boolean: {} } },
    ];
  }

  private _data(): Record<string, unknown> {
    const c = this._config;
    return {
      title: c?.title ?? "",
      project: c?.project ?? "",
      chart: c?.chart ?? "months",
      period: c?.period ?? "month",
      payer: typeof c?.payer === "number" ? String(c.payer) : "",
      category: typeof c?.category === "number" ? String(c.category) : "",
      include_reimbursements: c?.include_reimbursements ?? false,
      show_total: c?.show_total ?? true,
    };
  }

  private _changed(event: CustomEvent<{ value: Record<string, unknown> }>): void {
    event.stopPropagation();
    const value = event.detail.value;
    const config: CospendChartCardConfig = { ...(this._config as CospendChartCardConfig) };
    for (const key of ["title", "project"] as const) {
      const text = value[key];
      if (typeof text === "string" && text !== "") config[key] = text;
      else delete config[key];
    }
    // L'identifiant d'entrée n'a de sens qu'avec un projet choisi ; il se retrouve par le projet.
    const project = this._projects.find((p) => p.id === config.project);
    if (project) config.entry_id = project.entry_id;
    else delete config.entry_id;
    config.chart = (value.chart as ChartKind) || "months";
    config.period = (value.period as ChartPeriod) || "month";
    for (const key of ["payer", "category"] as const) {
      const raw = value[key];
      if (raw === "" || raw === undefined || raw === null) delete config[key];
      else config[key] = Number(raw);
    }
    config.include_reimbursements = value.include_reimbursements === true;
    config.show_total = value.show_total !== false;
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

customElements.define("cospend-chart-card-editor", CospendChartCardEditor);
