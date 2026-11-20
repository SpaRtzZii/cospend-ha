import { LitElement, css, html, nothing, svg } from "lit";
import type { PropertyValues, TemplateResult } from "lit";

import { errorMessage, fetchStatistics } from "./api";
import { categoryView, formatAmount, memberColor, memberName } from "./format";
import { translate } from "./i18n";
import {
  categoryColor,
  monthLabel,
  monthName,
  yearShown,
  percent,
  periodRange,
  sankeyLayout,
  type Period,
  type SankeyNodeIn,
} from "./stats-layout";
import type { HassLike, Project, Statistics, StatsFilters } from "./types";

type Tab = "table" | "chart" | "sankey";

const PERIODS: Period[] = [
  "all",
  "month",
  "last_month",
  "last_30",
  "year",
  "custom",
];
const MAX_LABEL = 18;
const NO_CATEGORY = 0;
/** En dessous de cette hauteur, un nœud du Sankey n'a pas la place d'afficher son libellé. */
const MIN_LABEL_HEIGHT = 9;

const clip = (text: string) =>
  text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 1)}…` : text;

/** Statistiques du projet : tableau, graphiques par mois et par catégorie, diagramme de Sankey. */
class CospendStats extends LitElement {
  static properties = {
    hass: { attribute: false },
    project: { attribute: false },
    _stats: { state: true },
    _loading: { state: true },
    _error: { state: true },
    _tab: { state: true },
    _showFilters: { state: true },
    _period: { state: true },
    _from: { state: true },
    _to: { state: true },
    _payer: { state: true },
    _ower: { state: true },
    _category: { state: true },
    _mode: { state: true },
    _reimbursements: { state: true },
  };

  declare hass?: HassLike;
  declare project?: Project;
  declare _stats: Statistics | null;
  declare _loading: boolean;
  declare _error: string;
  declare _tab: Tab;
  declare _showFilters: boolean;
  declare _period: Period;
  declare _from: string;
  declare _to: string;
  declare _payer: string;
  declare _ower: string;
  declare _category: string;
  declare _mode: string;
  declare _reimbursements: boolean;

  private _request = 0;

  constructor() {
    super();
    this._stats = null;
    this._loading = false;
    this._error = "";
    this._tab = "table";
    this._showFilters = false;
    this._period = "all";
    this._from = "";
    this._to = "";
    this._payer = "";
    this._ower = "";
    this._category = "";
    this._mode = "";
    this._reimbursements = false;
  }

  private get _lang(): string | undefined {
    return this.hass?.locale?.language ?? this.hass?.language;
  }

  private _t(key: string, vars: Record<string, string | number> = {}): string {
    return translate(this._lang, key, vars);
  }

  private _money(value: number, sign = false): string {
    return formatAmount(value, this.project?.currency, this._lang, { sign });
  }

  protected willUpdate(changed: PropertyValues): void {
    // Le projet est remplacé à chaque mise à jour des données : les chiffres suivent.
    if (changed.has("project") && this.project && this.hass) void this._load();
  }

  /** Critères envoyés au serveur, d'après l'état des champs. */
  private _filters(): StatsFilters {
    const filters: StatsFilters = {};
    const range =
      this._period === "custom"
        ? { from: this._from || undefined, to: this._to || undefined }
        : periodRange(this._period);
    if (range.from) filters.date_from = range.from;
    if (range.to) filters.date_to = range.to;
    if (this._payer !== "") filters.payer_id = Number(this._payer);
    if (this._ower !== "") filters.ower_id = Number(this._ower);
    if (this._category !== "") filters.category_id = Number(this._category);
    if (this._mode !== "") filters.payment_mode_id = Number(this._mode);
    if (this._reimbursements) filters.include_reimbursements = true;
    return filters;
  }

  private async _load(): Promise<void> {
    if (!this.hass || !this.project) return;
    const ticket = ++this._request;
    this._loading = true;
    try {
      const stats = await fetchStatistics(
        this.hass,
        this.project,
        this._filters(),
      );
      if (ticket !== this._request) return;
      this._stats = stats;
      this._error = "";
    } catch (error) {
      if (ticket !== this._request) return;
      this._error = this._t("stats_error", { message: errorMessage(error) });
    } finally {
      if (ticket === this._request) this._loading = false;
    }
  }

  private _close = (): void => {
    this.dispatchEvent(
      new CustomEvent("close", { bubbles: true, composed: true }),
    );
  };

  private _reset(): void {
    this._period = "all";
    this._from = "";
    this._to = "";
    this._payer = "";
    this._ower = "";
    this._category = "";
    this._mode = "";
    this._reimbursements = false;
    void this._load();
  }

  private _hasFilters(): boolean {
    return (
      this._period !== "all" ||
      this._payer !== "" ||
      this._ower !== "" ||
      this._category !== "" ||
      this._mode !== "" ||
      this._reimbursements
    );
  }

  // ------------------------------------------------------------------ libellés

  private _categoryName(id: number): string {
    return (
      categoryView(this.project!, id, this._t("reimbursement"))?.name ??
      this._t("no_category")
    );
  }

  private _modeName(id: number): string {
    return (
      this.project!.payment_modes.find((m) => m.id === id)?.name ??
      this._t("stats_no_mode")
    );
  }

  // ------------------------------------------------------------------ rendu

  protected render(): TemplateResult {
    if (!this.project) return html``;
    const stats = this._stats;
    return html`
      <div class="wrap">
        <div class="top">
          <button
            class="icon back"
            aria-label=${this._t("back")}
            @click=${this._close}
          >
            <ha-icon icon="mdi:arrow-left"></ha-icon>
          </button>
          <h2>${this._t("stats_title")}</h2>
          <button
            class="icon toggle ${this._hasFilters() ? "active" : ""}"
            aria-label=${this._t("stats_filters")}
            aria-expanded=${this._showFilters ? "true" : "false"}
            title=${this._t("stats_filters")}
            @click=${() => (this._showFilters = !this._showFilters)}
          >
            <ha-icon icon="mdi:filter-variant"></ha-icon>
          </button>
        </div>
        ${this._showFilters ? this._renderFilters() : nothing}
        ${this._error ? html`<p class="error" role="alert">${this._error}</p>` : nothing}
        ${
          stats && stats.pending > 0
            ? html`<p class="note warn">
                ${this._t("stats_pending", { count: stats.pending })}
              </p>`
            : nothing
        }
        ${!stats && this._loading ? html`<p class="hint">${this._t("stats_loading")}</p>` : nothing}
        ${stats ? this._renderBody(stats) : nothing}
      </div>
    `;
  }

  private _renderFilters(): TemplateResult {
    const project = this.project!;
    const select = (
      label: string,
      value: string,
      setter: (value: string) => void,
      options: Array<[string, string]>,
      name: string,
    ) =>
      html`<label class="field">
        <span>${label}</span>
        <select
          name=${name}
          .value=${value}
          @change=${(event: Event) => {
            setter((event.target as HTMLSelectElement).value);
            void this._load();
          }}
        >
          <option value="">${this._t("stats_any")}</option>
          ${options.map(([id, text]) => html`<option value=${id} ?selected=${id === value}>${text}</option>`)}
        </select>
      </label>`;
    const members: Array<[string, string]> = project.members.map((m) => [
      String(m.id),
      m.activated ? m.name : `${m.name} (${this._t("item_inactive")})`,
    ]);
    const categories: Array<[string, string]> = [
      [String(NO_CATEGORY), this._t("no_category")],
      ...project.categories.map((c): [string, string] => [
        String(c.id),
        `${c.icon} ${c.name}`.trim(),
      ]),
    ];
    const modes: Array<[string, string]> = project.payment_modes.map((m) => [
      String(m.id),
      `${m.icon} ${m.name}`.trim(),
    ]);
    return html`<div class="filters">
      <label class="field">
        <span>${this._t("stats_period")}</span>
        <select
          name="period"
          .value=${this._period}
          @change=${(event: Event) => {
            this._period = (event.target as HTMLSelectElement).value as Period;
            if (this._period !== "custom") void this._load();
          }}
        >
          ${PERIODS.map(
            (p) =>
              html`<option value=${p} ?selected=${p === this._period}>
                ${this._t(`period_${p}`)}
              </option>`,
          )}
        </select>
      </label>
      ${
        this._period === "custom"
          ? html`<label class="field">
                <span>${this._t("stats_from")}</span>
                <input
                  type="date"
                  name="from"
                  .value=${this._from}
                  @change=${(event: Event) => {
                    this._from = (event.target as HTMLInputElement).value;
                    void this._load();
                  }}
                />
              </label>
              <label class="field">
                <span>${this._t("stats_to")}</span>
                <input
                  type="date"
                  name="to"
                  .value=${this._to}
                  @change=${(event: Event) => {
                    this._to = (event.target as HTMLInputElement).value;
                    void this._load();
                  }}
                />
              </label>`
          : nothing
      }
      ${select(this._t("stats_payer"), this._payer, (v) => (this._payer = v), members, "payer")}
      ${select(this._t("stats_ower"), this._ower, (v) => (this._ower = v), members, "ower")}
      ${select(this._t("stats_category"), this._category, (v) => (this._category = v), categories, "category")}
      ${
        modes.length
          ? select(
              this._t("stats_mode"),
              this._mode,
              (v) => (this._mode = v),
              modes,
              "mode",
            )
          : nothing
      }
      <label class="check">
        <input
          type="checkbox"
          name="reimbursements"
          .checked=${this._reimbursements}
          @change=${(event: Event) => {
            this._reimbursements = (event.target as HTMLInputElement).checked;
            void this._load();
          }}
        />
        <span>${this._t("stats_reimbursements")}</span>
      </label>
      ${
        this._hasFilters()
          ? html`<button class="secondary reset" @click=${() => this._reset()}>
              ${this._t("stats_reset")}
            </button>`
          : nothing
      }
    </div>`;
  }

  private _renderBody(stats: Statistics): TemplateResult {
    const tabs: Array<[Tab, string]> = [
      ["table", "stats_tab_table"],
      ["chart", "stats_tab_chart"],
      ["sankey", "stats_tab_sankey"],
    ];
    return html`
      <div class="summary" aria-busy=${this._loading ? "true" : "false"}>
        <div>
          <span class="label">${this._t("stats_total")}</span>
          <strong class="total">${this._money(stats.total)}</strong>
        </div>
        <div>
          <span class="label">${this._t("stats_count")}</span>
          <strong class="count">${stats.count}</strong>
        </div>
      </div>
      <div class="tabs" role="tablist">
        ${tabs.map(
          ([tab, key]) =>
            html`<button
              role="tab"
              class="tab ${this._tab === tab ? "on" : ""}"
              data-tab=${tab}
              aria-selected=${this._tab === tab ? "true" : "false"}
              @click=${() => (this._tab = tab)}
            >
              ${this._t(key)}
            </button>`,
        )}
      </div>
      ${
        stats.count === 0
          ? html`<p class="hint empty">${this._t("stats_empty")}</p>`
          : this._tab === "table"
            ? this._renderTable(stats)
            : this._tab === "chart"
              ? this._renderCharts(stats)
              : this._renderSankey(stats)
      }
    `;
  }

  // ------------------------------------------------------------------ tableau

  private _renderTable(stats: Statistics): TemplateResult {
    const project = this.project!;
    const section = (
      title: string,
      rows: Array<{ name: string; value: number; color?: string }>,
    ) =>
      html`<section>
        <h3>${title}</h3>
        <table class="share">
          <tbody>
            ${rows.map(
              (row) =>
                html`<tr>
                  <td class="name">
                    ${
                      row.color
                        ? html`<span
                            class="dot"
                            style="background:${row.color}"
                          ></span>`
                        : nothing
                    }${row.name}
                  </td>
                  <td class="num">${this._money(row.value)}</td>
                  <td class="pct">${percent(row.value, stats.total)} %</td>
                </tr>`,
            )}
          </tbody>
        </table>
      </section>`;
    return html`
      <section>
        <h3>${this._t("stats_members")}</h3>
        <table class="members">
          <thead>
            <tr>
              <th></th>
              <th class="num">${this._t("stats_paid")}</th>
              <th class="num">${this._t("stats_spent")}</th>
              <th class="num">${this._t("stats_balance")}</th>
            </tr>
          </thead>
          <tbody>
            ${stats.members.map((m) => {
              const member = project.members.find((x) => x.id === m.id);
              return html`<tr>
                <td class="name">
                  <span
                    class="dot"
                    style="background:${member ? memberColor(member) : "#888"}"
                  ></span>
                  ${memberName(project, m.id)}
                </td>
                <td class="num">${this._money(m.paid)}</td>
                <td class="num">${this._money(m.spent)}</td>
                <td
                  class="num ${m.balance < -0.005 ? "neg" : m.balance > 0.005 ? "pos" : ""}"
                >
                  ${this._money(m.balance, true)}
                </td>
              </tr>`;
            })}
          </tbody>
        </table>
      </section>
      ${section(
        this._t("stats_categories"),
        stats.categories.map((c) => ({
          name: this._categoryName(c.id),
          value: c.total,
          color: categoryColor(project, c.id),
        })),
      )}
      ${
        stats.payment_modes.length > 1 ||
        stats.payment_modes.some((m) => m.id !== 0)
          ? section(
              this._t("stats_modes"),
              stats.payment_modes.map((m) => ({
                name: this._modeName(m.id),
                value: m.total,
              })),
            )
          : nothing
      }
      ${section(
        this._t("stats_months"),
        stats.months.map((m) => ({
          name: monthLabel(m.month, this._lang),
          value: m.total,
        })),
      )}
    `;
  }

  // ------------------------------------------------------------------ graphiques

  private _renderCharts(stats: Statistics): TemplateResult {
    const project = this.project!;
    const order = stats.categories.map((c) => c.id);
    const maxMonth = Math.max(...stats.months.map((m) => m.total), 1);
    const slot = 44;
    const height = 180;
    const top = 16;
    const bottom = 32;
    const plot = height - top - bottom;
    const width = Math.max(stats.months.length * slot + 40, 280);
    const bars = stats.months.map((m, index) => {
      let y = height - bottom;
      const x = 36 + index * slot;
      const segments = order
        .filter((id) => (m.by_category[String(id)] ?? 0) > 0)
        .map((id) => {
          const value = m.by_category[String(id)];
          const h = (value / maxMonth) * plot;
          y -= h;
          return svg`<rect x=${x} y=${y} width=${slot - 12} height=${Math.max(h, 0.5)}
            fill=${categoryColor(project, id)}>
            <title>${this._categoryName(id)} : ${this._money(value)}</title>
          </rect>`;
        });
      return svg`<g>${segments}
        <text x=${x + (slot - 12) / 2} y=${height - 18} text-anchor="middle" class="axis"
          >${monthName(m.month, this._lang)}</text>
        ${yearShown(stats.months, index)
          ? svg`<text x=${x + (slot - 12) / 2} y=${height - 6} text-anchor="middle" class="axis"
              >${m.month.slice(0, 4)}</text>`
          : nothing}
        <title>${monthLabel(m.month, this._lang)} : ${this._money(m.total)}</title>
      </g>`;
    });
    const biggest = stats.categories[0]?.total ?? 1;
    return html`
      <section>
        <h3>${this._t("stats_by_month")}</h3>
        <div class="scroll">
          <svg
            class="months"
            role="img"
            aria-label=${this._t("stats_by_month")}
            viewBox="0 0 ${width} ${height}"
            style="min-width:${width}px"
          >
            <text x="0" y=${top - 4} class="axis">
              ${this._money(maxMonth)}
            </text>
            <line
              x1="34"
              x2=${width}
              y1=${height - bottom}
              y2=${height - bottom}
              class="base"
            />
            ${bars}
          </svg>
        </div>
      </section>
      <section>
        <h3>${this._t("stats_by_category")}</h3>
        <ul class="bars">
          ${stats.categories.map(
            (c) =>
              html`<li>
                <span class="bar-name">${this._categoryName(c.id)}</span>
                <span class="bar-track"
                  ><span
                    class="bar-fill"
                    style="width:${Math.max((c.total / biggest) * 100, 1)}%;background:${categoryColor(project, c.id)}"
                  ></span
                ></span>
                <span class="bar-value">${this._money(c.total)}</span>
              </li>`,
          )}
        </ul>
      </section>
    `;
  }

  // ------------------------------------------------------------------ Sankey

  private _renderSankey(stats: Statistics): TemplateResult {
    const project = this.project!;
    const ids = new Set<string>();
    for (const link of stats.links) {
      ids.add(link.source);
      ids.add(link.target);
    }
    const nodes: SankeyNodeIn[] = [...ids].map((key) => {
      const [kind, raw] = key.split(":");
      const id = Number(raw);
      if (kind === "category") {
        return {
          id: key,
          label: this._categoryName(id),
          color: categoryColor(project, id),
          column: 1,
        };
      }
      const member = project.members.find((m) => m.id === id);
      return {
        id: key,
        label: memberName(project, id),
        color: member ? memberColor(member) : "#888888",
        column: kind === "payer" ? 0 : 2,
      };
    });
    const width = 480;
    const margin = 0;
    const tallest = Math.max(
      ...[0, 1, 2].map((column) => nodes.filter((n) => n.column === column).length),
    );
    const padding = 12;
    const height = Math.min(Math.max(tallest * 30 + 2 * padding, 220), 560);
    const layout = sankeyLayout(nodes, stats.links, {
      width,
      height,
      margin,
      padding,
      gap: 8,
      nodeWidth: 12,
    });
    const name = new Map(nodes.map((n) => [n.id, n.label]));
    return html`
      <section>
        <p class="hint">${this._t("stats_sankey_hint")}</p>
        <div class="scroll">
          <svg
            class="sankey"
            role="img"
            aria-label=${this._t("stats_tab_sankey")}
            viewBox="0 0 ${width} ${height}"
            style="min-width:420px"
          >
            ${layout.links.map(
              (l) => svg`<path d=${l.path} fill="none" stroke=${l.color}
                stroke-width=${l.width} stroke-opacity="0.35">
                <title>${name.get(l.source)} → ${name.get(l.target)} : ${this._money(l.value)}</title>
              </path>`,
            )}
            ${layout.nodes.map((n) => {
              const left = n.column === 2;
              return svg`<g>
                <rect x=${n.x} y=${n.y} width="12" height=${Math.max(n.height, 1)} fill=${n.color}>
                  <title>${n.label} : ${this._money(n.value)}</title>
                </rect>
                ${n.height < MIN_LABEL_HEIGHT
                  ? nothing
                  : svg`<text
                  x=${left ? n.x - 6 : n.x + 18}
                  y=${n.y + n.height / 2}
                  dy="0.35em"
                  text-anchor=${left ? "end" : "start"}
                  class="label-node"
                  >${clip(n.label)}</text
                >`}
              </g>`;
            })}
          </svg>
        </div>
      </section>
    `;
  }

  static styles = css`
    :host {
      display: block;
    }
    .wrap {
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding: 4px 16px 12px;
    }
    .top {
      display: flex;
      align-items: center;
      gap: 4px;
    }
    h2 {
      flex: 1;
      margin: 0;
      font-size: 1.25rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    h3 {
      margin: 8px 0 4px;
      font-size: 0.8rem;
      font-weight: 500;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--secondary-text-color);
    }
    button {
      font: inherit;
      cursor: pointer;
    }
    button:focus-visible,
    select:focus-visible,
    input:focus-visible {
      outline: 2px solid var(--primary-color);
      outline-offset: 1px;
    }
    button.icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 36px;
      height: 36px;
      padding: 0;
      color: var(--secondary-text-color);
      background: none;
      border: none;
      border-radius: 50%;
    }
    button.icon:hover {
      background: var(--secondary-background-color);
    }
    button.icon.active {
      color: var(--primary-color);
    }
    button.secondary {
      padding: 6px 14px;
      color: var(--primary-color);
      background: none;
      border: 1px solid var(--primary-color);
      border-radius: 18px;
    }
    .filters {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px 12px;
      align-items: end;
      padding: 12px;
      border-radius: 8px;
      background: var(--secondary-background-color);
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    select,
    input[type="date"] {
      font: inherit;
      padding: 6px 8px;
      color: var(--primary-text-color);
      background: var(--card-background-color, #fff);
      border: 1px solid var(--divider-color);
      border-radius: 6px;
      min-width: 0;
    }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--primary-text-color);
    }
    .summary {
      display: flex;
      gap: 24px;
    }
    .label {
      display: block;
      font-size: 0.8rem;
      color: var(--secondary-text-color);
    }
    .total {
      font-size: 1.5rem;
      font-weight: 500;
      color: var(--primary-text-color);
    }
    .count {
      font-size: 1.5rem;
      font-weight: 400;
      color: var(--primary-text-color);
    }
    .tabs {
      display: flex;
      border-bottom: 1px solid var(--divider-color);
    }
    .tab {
      flex: 1;
      padding: 8px 4px;
      color: var(--secondary-text-color);
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
    }
    .tab.on {
      color: var(--primary-color);
      border-bottom-color: var(--primary-color);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      color: var(--primary-text-color);
    }
    th {
      font-size: 0.75rem;
      font-weight: 500;
      color: var(--secondary-text-color);
      text-align: right;
      padding: 4px 0;
    }
    td {
      padding: 6px 0;
      border-bottom: 1px solid var(--divider-color);
    }
    .num {
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
      padding-left: 8px;
    }
    .pct {
      width: 3.5em;
      text-align: right;
      color: var(--secondary-text-color);
      font-variant-numeric: tabular-nums;
      padding-left: 8px;
    }
    .pos {
      color: var(--success-color, #43a047);
    }
    .neg {
      color: var(--error-color, #db4437);
    }
    .dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      margin-right: 8px;
      border-radius: 50%;
    }
    .dot.gray {
      background: var(--secondary-text-color);
      opacity: 0.5;
    }
    .scroll {
      overflow-x: auto;
    }
    svg {
      display: block;
      width: 100%;
      height: auto;
    }
    svg .axis {
      font-size: 10px;
      fill: var(--secondary-text-color);
    }
    svg .base {
      stroke: var(--divider-color);
    }
    svg .label-node {
      font-size: 12px;
      fill: var(--primary-text-color);
      paint-order: stroke;
      stroke: var(--card-background-color, #fff);
      stroke-width: 3px;
      stroke-linejoin: round;
    }
    ul.bars {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    ul.bars li {
      display: grid;
      grid-template-columns: minmax(70px, 28%) 1fr auto;
      align-items: center;
      gap: 8px;
      color: var(--primary-text-color);
    }
    .bar-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .bar-track {
      height: 12px;
      border-radius: 6px;
      background: var(--secondary-background-color);
      overflow: hidden;
    }
    .bar-fill {
      display: block;
      height: 100%;
      border-radius: 6px;
    }
    .bar-value {
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .note,
    .hint {
      margin: 0;
      color: var(--secondary-text-color);
    }
    .note.warn {
      color: var(--warning-color);
    }
    .empty {
      padding: 16px 0;
      text-align: center;
    }
    .error {
      margin: 0;
      padding: 8px 12px;
      border-radius: 8px;
      color: var(--error-color);
      background: color-mix(in srgb, var(--error-color) 12%, transparent);
    }
  `;
}

customElements.define("cospend-stats", CospendStats);
