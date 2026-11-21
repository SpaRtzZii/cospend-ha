// Graphiques partagés par la vue Statistiques de la carte principale et par la carte dédiée.

import { css, html, nothing, svg } from "lit";
import type { TemplateResult } from "lit";

import { categoryView, memberColor, memberName } from "./format";
import {
  categoryColor,
  monthLabel,
  monthName,
  sankeyLayout,
  yearShown,
  type SankeyNodeIn,
} from "./stats-layout";
import type { Project, Statistics } from "./types";

export interface ChartContext {
  project: Project;
  stats: Statistics;
  lang?: string;
  /** Texte traduit (les clés sont celles de ``i18n.ts``). */
  t: (key: string) => string;
  /** Montant dans la devise du projet. */
  money: (value: number) => string;
}

const MAX_LABEL = 18;
/** En dessous de cette hauteur, un nœud du Sankey n'a pas la place d'afficher son libellé. */
const MIN_LABEL_HEIGHT = 9;

const clip = (text: string) => (text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 1)}…` : text);

export function categoryName(ctx: ChartContext, id: number): string {
  return categoryView(ctx.project, id, ctx.t("reimbursement"))?.name ?? ctx.t("no_category");
}

/** Dépenses par mois, empilées par catégorie. */
export function monthsChart(ctx: ChartContext): TemplateResult {
  const { project, stats } = ctx;
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
          <title>${categoryName(ctx, id)} : ${ctx.money(value)}</title>
        </rect>`;
      });
    return svg`<g>${segments}
      <text x=${x + (slot - 12) / 2} y=${height - 18} text-anchor="middle" class="axis"
        >${monthName(m.month, ctx.lang)}</text>
      ${yearShown(stats.months, index)
        ? svg`<text x=${x + (slot - 12) / 2} y=${height - 6} text-anchor="middle" class="axis"
            >${m.month.slice(0, 4)}</text>`
        : nothing}
      <title>${monthLabel(m.month, ctx.lang)} : ${ctx.money(m.total)}</title>
    </g>`;
  });
  return html`<div class="scroll">
    <svg
      class="months"
      role="img"
      aria-label=${ctx.t("stats_by_month")}
      viewBox="0 0 ${width} ${height}"
      style="min-width:${width}px"
    >
      <text x="0" y=${top - 4} class="axis">${ctx.money(maxMonth)}</text>
      <line x1="34" x2=${width} y1=${height - bottom} y2=${height - bottom} class="base" />
      ${bars}
    </svg>
  </div>
  <ul class="legend">
    ${order.map(
      (id) => html`<li>
        <span class="dot" style="background:${categoryColor(project, id)}"></span
        >${categoryName(ctx, id)}
      </li>`,
    )}
  </ul>`;
}

/** Dépenses par catégorie : une barre par catégorie, la plus grosse en premier. */
export function categoryBars(ctx: ChartContext): TemplateResult {
  const biggest = ctx.stats.categories[0]?.total ?? 1;
  return html`<ul class="bars">
    ${ctx.stats.categories.map(
      (c) => html`<li>
        <span class="bar-name">${categoryName(ctx, c.id)}</span>
        <span class="bar-track"
          ><span
            class="bar-fill"
            style="width:${Math.max((c.total / biggest) * 100, 1)}%;background:${categoryColor(ctx.project, c.id)}"
          ></span
        ></span>
        <span class="bar-value">${ctx.money(c.total)}</span>
      </li>`,
    )}
  </ul>`;
}

/** Par membre : ce qu'il a payé (barre pleine) et sa part des dépenses (barre claire). */
export function membersBars(ctx: ChartContext): TemplateResult {
  const { project, stats } = ctx;
  const biggest = Math.max(...stats.members.flatMap((m) => [m.paid, m.spent]), 1);
  const rows = [...stats.members].sort((a, b) => b.paid - a.paid);
  return html`<ul class="bars members">
      ${rows.map((m) => {
        const member = project.members.find((x) => x.id === m.id);
        const color = member ? memberColor(member) : "#888888";
        return html`<li>
          <span class="bar-name">${memberName(project, m.id)}</span>
          <span class="bar-pair">
            <span class="bar-track"
              ><span
                class="bar-fill paid"
                style="width:${Math.max((m.paid / biggest) * 100, m.paid > 0 ? 1 : 0)}%;background:${color}"
              ></span
            ></span>
            <span class="bar-track"
              ><span
                class="bar-fill spent"
                style="width:${Math.max((m.spent / biggest) * 100, m.spent > 0 ? 1 : 0)}%;background:${color}"
              ></span
            ></span>
          </span>
          <span class="bar-value">
            ${ctx.money(m.paid)}<small>${ctx.money(m.spent)}</small>
          </span>
        </li>`;
      })}
    </ul>
    <p class="legend-line">
      <span class="swatch solid"></span>${ctx.t("stats_paid")}
      <span class="swatch light"></span>${ctx.t("stats_spent")}
    </p>`;
}

/** Diagramme de Sankey : qui a payé, dans quelle catégorie, pour qui. */
export function sankeyChart(ctx: ChartContext): TemplateResult {
  const { project, stats } = ctx;
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
        label: categoryName(ctx, id),
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
  const tallest = Math.max(
    ...[0, 1, 2].map((column) => nodes.filter((n) => n.column === column).length),
  );
  const padding = 12;
  const height = Math.min(Math.max(tallest * 30 + 2 * padding, 220), 560);
  const layout = sankeyLayout(nodes, stats.links, {
    width,
    height,
    margin: 0,
    padding,
    gap: 8,
    nodeWidth: 12,
  });
  const name = new Map(nodes.map((n) => [n.id, n.label]));
  return html`<div class="scroll">
    <svg
      class="sankey"
      role="img"
      aria-label=${ctx.t("stats_tab_sankey")}
      viewBox="0 0 ${width} ${height}"
      style="min-width:420px"
    >
      ${layout.links.map(
        (l) => svg`<path d=${l.path} fill="none" stroke=${l.color}
          stroke-width=${l.width} stroke-opacity="0.35">
          <title>${name.get(l.source)} → ${name.get(l.target)} : ${ctx.money(l.value)}</title>
        </path>`,
      )}
      ${layout.nodes.map((n) => {
        const left = n.column === 2;
        return svg`<g>
          <rect x=${n.x} y=${n.y} width="12" height=${Math.max(n.height, 1)} fill=${n.color}>
            <title>${n.label} : ${ctx.money(n.value)}</title>
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
  </div>`;
}

export const chartStyles = css`
  ul.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
    list-style: none;
    margin: 8px 0 0;
    padding: 0;
    font-size: 0.8rem;
    color: var(--secondary-text-color);
  }
  ul.legend .dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    margin-right: 6px;
    border-radius: 50%;
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
  .bar-pair {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .bar-track {
    height: 12px;
    border-radius: 6px;
    background: var(--secondary-background-color);
    overflow: hidden;
  }
  ul.bars.members .bar-track {
    height: 8px;
    border-radius: 4px;
  }
  .bar-fill {
    display: block;
    height: 100%;
    border-radius: inherit;
  }
  .bar-fill.spent {
    opacity: 0.45;
  }
  .bar-value {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    text-align: right;
  }
  .bar-value small {
    display: block;
    color: var(--secondary-text-color);
  }
  .legend-line {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 8px 0 0;
    font-size: 0.8rem;
    color: var(--secondary-text-color);
  }
  .swatch {
    display: inline-block;
    width: 18px;
    height: 8px;
    border-radius: 4px;
    background: var(--secondary-text-color);
  }
  .swatch.light {
    margin-left: 12px;
    opacity: 0.45;
  }
`;
