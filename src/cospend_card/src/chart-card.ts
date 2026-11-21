import { LitElement, css, html, nothing } from "lit";
import type { TemplateResult } from "lit";

import { errorMessage, fetchProjects, fetchStatistics, subscribeChanges } from "./api";
import {
  categoryBars,
  chartStyles,
  membersBars,
  monthsChart,
  sankeyChart,
  type ChartContext,
} from "./charts";
import { formatAmount } from "./format";
import { translate } from "./i18n";
import { periodRange } from "./stats-layout";
import type {
  ChartKind,
  CospendChartCardConfig,
  HassLike,
  Project,
  Statistics,
  StatsFilters,
} from "./types";
import "./balances";
import "./chart-card-editor";

const REFRESH_DELAY_MS = 500;
const KINDS: ChartKind[] = ["months", "categories", "members", "flows", "balances"];

const TITLE_KEY: Record<ChartKind, string> = {
  months: "stats_by_month",
  categories: "stats_by_category",
  members: "stats_members",
  flows: "chart_flows",
  balances: "balances",
};

/** Carte autonome : un seul graphique du projet Cospend, avec sa période et ses filtres. */
class CospendChartCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
    _project: { state: true },
    _stats: { state: true },
    _loading: { state: true },
    _failed: { state: true },
    _error: { state: true },
  };

  declare hass?: HassLike;
  declare _config?: CospendChartCardConfig;
  declare _project: Project | null;
  declare _stats: Statistics | null;
  declare _loading: boolean;
  declare _failed: boolean;
  declare _error: string;

  private _unsubscribe?: () => void;
  private _subscribing = false;
  private _started = false;
  private _refreshTimer?: ReturnType<typeof setTimeout>;
  private _request = 0;

  constructor() {
    super();
    this._project = null;
    this._stats = null;
    this._loading = false;
    this._failed = false;
    this._error = "";
  }

  static getConfigElement(): HTMLElement {
    return document.createElement("cospend-chart-card-editor");
  }

  static getStubConfig(): Partial<CospendChartCardConfig> {
    return { chart: "months", period: "month" };
  }

  setConfig(config: CospendChartCardConfig): void {
    if (config.chart !== undefined && !KINDS.includes(config.chart)) {
      throw new Error(`chart: ${KINDS.join(", ")}`);
    }
    this._config = { ...config };
    if (this._started) void this._load();
  }

  getCardSize(): number {
    return this._kind === "balances" ? 3 : 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 3 };
  }

  // ------------------------------------------------------------------ cycle de vie

  connectedCallback(): void {
    super.connectedCallback();
    if (this.hass) void this._start();
  }

  disconnectedCallback(): void {
    super.disconnectedCallback();
    this._unsubscribe?.();
    this._unsubscribe = undefined;
    this._subscribing = false;
    this._started = false;
    clearTimeout(this._refreshTimer);
  }

  protected willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("hass") && this.hass && this.isConnected && !this._started) {
      void this._start();
    }
  }

  private async _start(): Promise<void> {
    if (this._started || !this.hass) return;
    this._started = true;
    await this._load();
    await this._subscribe();
  }

  private async _subscribe(): Promise<void> {
    if (!this.hass || this._unsubscribe || this._subscribing) return;
    this._subscribing = true;
    try {
      const unsubscribe = await subscribeChanges(this.hass, () => {
        clearTimeout(this._refreshTimer);
        this._refreshTimer = setTimeout(() => void this._load(true), REFRESH_DELAY_MS);
      });
      if (this._started) this._unsubscribe = unsubscribe;
      else unsubscribe();
    } catch {
      // Sans abonnement la carte fonctionne, mais ne se met pas à jour toute seule.
    } finally {
      this._subscribing = false;
    }
  }

  // ------------------------------------------------------------------ données

  private get _kind(): ChartKind {
    return this._config?.chart ?? "months";
  }

  private get _lang(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this._lang, key, vars);
  }

  private _pickProject(projects: Project[]): Project | null {
    const wanted = this._config?.project;
    if (wanted) {
      return (
        projects.find(
          (p) => p.id === wanted && (!this._config?.entry_id || p.entry_id === this._config.entry_id),
        ) ?? null
      );
    }
    return projects.find((p) => !p.archived) ?? null;
  }

  private _filters(): StatsFilters {
    const config = this._config;
    const filters: StatsFilters = {};
    const range = periodRange(config?.period ?? "month");
    if (range.from) filters.date_from = range.from;
    if (range.to) filters.date_to = range.to;
    if (typeof config?.payer === "number") filters.payer_id = config.payer;
    if (typeof config?.category === "number") filters.category_id = config.category;
    if (config?.include_reimbursements === true) filters.include_reimbursements = true;
    return filters;
  }

  /** ``quiet`` : mise à jour en arrière-plan, sans effacer ce qui est affiché. */
  private async _load(quiet = false): Promise<void> {
    if (!this.hass) return;
    const ticket = ++this._request;
    if (!quiet) this._loading = true;
    try {
      const project = this._pickProject(await fetchProjects(this.hass));
      const stats =
        project && this._kind !== "balances"
          ? await fetchStatistics(this.hass, project, this._filters())
          : null;
      if (ticket !== this._request) return;
      this._project = project;
      this._stats = stats;
      this._failed = false;
      this._error = "";
    } catch (error) {
      if (ticket !== this._request) return;
      if (!quiet) {
        this._failed = true;
        this._error = errorMessage(error);
      }
    } finally {
      if (ticket === this._request) this._loading = false;
    }
  }

  // ------------------------------------------------------------------ rendu

  private _money(value: number): string {
    return formatAmount(value, this._project?.currency, this._lang);
  }

  private _context(stats: Statistics): ChartContext {
    return {
      project: this._project!,
      stats,
      lang: this._lang,
      t: (key) => this._t(key),
      money: (value) => this._money(value),
    };
  }

  private _body(): TemplateResult | typeof nothing {
    const project = this._project;
    if (this._failed && !project) {
      return html`<p class="error" role="alert">${this._t("error")}
        ${this._error ? html`<small>${this._error}</small>` : nothing}
        <button class="retry" @click=${() => void this._load()}>${this._t("retry")}</button></p>`;
    }
    if (!project) {
      return html`<p class="hint">${this._loading ? this._t("loading") : this._t("no_projects")}</p>`;
    }
    if (this._kind === "balances") {
      return html`<cospend-balances inline .hass=${this.hass} .project=${project}></cospend-balances>`;
    }
    const stats = this._stats;
    if (!stats) return html`<p class="hint">${this._t("stats_loading")}</p>`;
    if (stats.count === 0) return html`<p class="hint empty">${this._t("stats_empty")}</p>`;
    const ctx = this._context(stats);
    switch (this._kind) {
      case "categories":
        return categoryBars(ctx);
      case "members":
        return membersBars(ctx);
      case "flows":
        return sankeyChart(ctx);
      default:
        return monthsChart(ctx);
    }
  }

  protected render(): TemplateResult {
    if (!this._config) return html``;
    const kind = this._kind;
    const project = this._project;
    const stats = this._stats;
    const title = this._config.title ?? this._t(TITLE_KEY[kind]);
    const period = this._config.period ?? "month";
    const showSummary = kind !== "balances" && this._config.show_total !== false && stats;
    return html`
      <ha-card>
        <div class="header">
          <div class="title">${title}</div>
          ${kind !== "balances"
            ? html`<span class="chip">${this._t(`period_${period}`)}</span>`
            : nothing}
        </div>
        ${project && !this._config.title
          ? html`<div class="subtitle">${project.name}</div>`
          : nothing}
        ${showSummary
          ? html`<div class="summary">
              <strong class="total">${this._money(stats.total)}</strong>
              <span class="count">${this._t("stats_count_value", { count: stats.count })}</span>
            </div>`
          : nothing}
        <div class="content" aria-busy=${this._loading ? "true" : "false"}>${this._body()}</div>
      </ha-card>
    `;
  }

  static styles = [
    chartStyles,
    css`
      :host {
        display: block;
      }
      ha-card {
        height: 100%;
        box-sizing: border-box;
        padding-bottom: 16px;
      }
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 16px 16px 0;
      }
      .title {
        font-size: 1.25rem;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .subtitle {
        padding: 0 16px;
        font-size: 0.85rem;
        color: var(--secondary-text-color);
      }
      .chip {
        flex: none;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        color: var(--secondary-text-color);
        background: var(--secondary-background-color);
      }
      .summary {
        display: flex;
        align-items: baseline;
        gap: 12px;
        padding: 8px 16px 0;
      }
      .total {
        font-size: 1.5rem;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .count {
        font-size: 0.85rem;
        color: var(--secondary-text-color);
      }
      .content {
        padding: 12px 16px 0;
      }
      .hint {
        margin: 0;
        color: var(--secondary-text-color);
      }
      .hint.empty {
        padding: 16px 0;
        text-align: center;
      }
      .error {
        margin: 0;
        color: var(--error-color);
      }
      .error small {
        display: block;
        color: var(--secondary-text-color);
      }
      .retry {
        margin-top: 8px;
        padding: 6px 14px;
        font: inherit;
        color: var(--primary-color);
        background: none;
        border: 1px solid var(--primary-color);
        border-radius: 18px;
        cursor: pointer;
      }
    `,
  ];
}

customElements.define("cospend-chart-card", CospendChartCard);

window.customCards = window.customCards ?? [];
window.customCards.push({
  type: "cospend-chart-card",
  name: "Cospend — graphique",
  description:
    "Un graphique de vos dépenses Cospend (par mois, catégorie, membre, flux, soldes). / One Cospend chart.",
  preview: false,
  documentationURL: "https://github.com/SpaRtzZii/cospend-ha",
});
