// Calculs de la vue Statistiques : périodes, couleurs, géométrie du diagramme de Sankey.

import type { Project, StatsLink } from "./types";

export type Period =
  "all" | "month" | "last_month" | "last_30" | "year" | "custom";

const pad = (value: number) => String(value).padStart(2, "0");
const iso = (date: Date) =>
  `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

/** Bornes (AAAA-MM-JJ, incluses) d'une période prédéfinie ; ``{}`` pour « toute la période ». */
export function periodRange(
  period: Period,
  now: Date = new Date(),
): { from?: string; to?: string } {
  const y = now.getFullYear();
  const m = now.getMonth();
  switch (period) {
    case "month":
      return { from: iso(new Date(y, m, 1)), to: iso(new Date(y, m + 1, 0)) };
    case "last_month":
      return { from: iso(new Date(y, m - 1, 1)), to: iso(new Date(y, m, 0)) };
    case "last_30":
      return {
        from: iso(new Date(y, now.getMonth(), now.getDate() - 29)),
        to: iso(now),
      };
    case "year":
      return { from: `${y}-01-01`, to: `${y}-12-31` };
    default:
      return {};
  }
}

/** Couleurs de repli (lisibles en clair comme en sombre) pour les catégories sans couleur. */
export const PALETTE = [
  "#4e79a7",
  "#f28e2b",
  "#59a14f",
  "#e15759",
  "#76b7b2",
  "#edc948",
  "#b07aa1",
  "#ff9da7",
  "#9c755f",
  "#8cd17d",
];

export function categoryColor(
  project: Pick<Project, "categories">,
  id: number,
): string {
  const index = project.categories.findIndex((c) => c.id === id);
  const own = index >= 0 ? project.categories[index].color : "";
  if (/^#[0-9a-f]{3,8}$/i.test(own)) return own;
  return PALETTE[(index >= 0 ? index : PALETTE.length - 1) % PALETTE.length];
}

/** « 2026-11 » devient « nov. 2026 » dans la langue donnée. */
export function monthLabel(month: string, language = "en"): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return month;
  return new Intl.DateTimeFormat(language || "en", {
    month: "short",
    year: "numeric",
  }).format(new Date(Number(match[1]), Number(match[2]) - 1, 1));
}

/** « 2026-11 » devient « nov. » : le mois seul, l'année étant affichée à part. */
export function monthName(month: string, language = "en"): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return month;
  return new Intl.DateTimeFormat(language || "en", { month: "short" }).format(
    new Date(Number(match[1]), Number(match[2]) - 1, 1),
  );
}

/** Vrai quand l'année doit figurer sous le mois : premier mois, ou changement d'année. */
export function yearShown(months: Array<{ month: string }>, index: number): boolean {
  return index === 0 || months[index].month.slice(0, 4) !== months[index - 1].month.slice(0, 4);
}

/** Part de ``value`` dans ``total``, en pourcentage entier (0 si le total est nul). */
export function percent(value: number, total: number): number {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}

// ---------------------------------------------------------------------- Sankey

export interface SankeyNodeIn {
  id: string;
  label: string;
  color: string;
  column: number;
}

export interface SankeyNode extends SankeyNodeIn {
  value: number;
  x: number;
  y: number;
  height: number;
}

export interface SankeyLink {
  source: string;
  target: string;
  value: number;
  /** Courbe de Bézier à tracer avec un trait de largeur ``width``. */
  path: string;
  width: number;
  color: string;
}

export interface SankeyLayout {
  nodes: SankeyNode[];
  links: SankeyLink[];
}

export interface SankeyOptions {
  width: number;
  height: number;
  nodeWidth?: number;
  gap?: number;
  /** Marge de chaque côté, réservée aux libellés. */
  margin?: number;
  /** Marge en haut et en bas, pour que les libellés des nœuds extrêmes ne soient pas coupés. */
  padding?: number;
}

/**
 * Place les nœuds en colonnes et trace les flux. Chaque nœud a la hauteur de son flux le plus
 * important (entrant ou sortant) ; toutes les colonnes partagent la même échelle pour que
 * l'épaisseur d'un flux reste comparable d'un bout à l'autre.
 */
export function sankeyLayout(
  nodesIn: SankeyNodeIn[],
  linksIn: StatsLink[],
  options: SankeyOptions,
): SankeyLayout {
  const nodeWidth = options.nodeWidth ?? 12;
  const gap = options.gap ?? 8;
  const margin = options.margin ?? 0;
  const padding = options.padding ?? 0;
  const room = options.height - 2 * padding;
  const known = new Set(nodesIn.map((n) => n.id));
  const links = linksIn.filter(
    (l) => l.value > 0 && known.has(l.source) && known.has(l.target),
  );

  const incoming = new Map<string, number>();
  const outgoing = new Map<string, number>();
  for (const l of links) {
    outgoing.set(l.source, (outgoing.get(l.source) ?? 0) + l.value);
    incoming.set(l.target, (incoming.get(l.target) ?? 0) + l.value);
  }
  const used = nodesIn
    .map((n) => ({
      ...n,
      value: Math.max(incoming.get(n.id) ?? 0, outgoing.get(n.id) ?? 0),
    }))
    .filter((n) => n.value > 0);
  if (used.length === 0) return { nodes: [], links: [] };

  const columns = [...new Set(used.map((n) => n.column))].sort((a, b) => a - b);
  const byColumn = new Map(
    columns.map((c) => [
      c,
      used.filter((n) => n.column === c).sort((a, b) => b.value - a.value),
    ]),
  );

  // Échelle commune : la colonne la plus contrainte (beaucoup de nœuds) fixe le facteur.
  let scale = Infinity;
  for (const list of byColumn.values()) {
    const free = room - gap * (list.length - 1);
    const sum = list.reduce((acc, n) => acc + n.value, 0);
    scale = Math.min(scale, Math.max(free, 1) / sum);
  }

  const span = options.width - 2 * margin - nodeWidth;
  const step = columns.length > 1 ? span / (columns.length - 1) : 0;
  const placed = new Map<string, SankeyNode>();
  columns.forEach((column, index) => {
    const list = byColumn.get(column)!;
    const total =
      list.reduce((acc, n) => acc + n.value * scale, 0) +
      gap * (list.length - 1);
    let y = padding + (room - total) / 2;
    for (const node of list) {
      const height = node.value * scale;
      placed.set(node.id, { ...node, x: margin + index * step, y, height });
      y += height + gap;
    }
  });

  // Les flux sortent et arrivent dans l'ordre vertical des nœuds voisins : moins de croisements.
  const outOffset = new Map<string, number>();
  const inOffset = new Map<string, number>();
  const order = (a: StatsLink, b: StatsLink) =>
    placed.get(a.target)!.y - placed.get(b.target)!.y ||
    placed.get(a.source)!.y - placed.get(b.source)!.y;
  const bySource = [...links].sort(order);
  const byTarget = [...links].sort(
    (a, b) =>
      placed.get(a.source)!.y - placed.get(b.source)!.y ||
      placed.get(a.target)!.y - placed.get(b.target)!.y,
  );
  const sourceY = new Map<StatsLink, number>();
  const targetY = new Map<StatsLink, number>();
  for (const l of bySource) {
    const node = placed.get(l.source)!;
    const offset = outOffset.get(l.source) ?? 0;
    sourceY.set(l, node.y + offset + (l.value * scale) / 2);
    outOffset.set(l.source, offset + l.value * scale);
  }
  for (const l of byTarget) {
    const node = placed.get(l.target)!;
    const offset = inOffset.get(l.target) ?? 0;
    targetY.set(l, node.y + offset + (l.value * scale) / 2);
    inOffset.set(l.target, offset + l.value * scale);
  }

  const round = (value: number) => Math.round(value * 100) / 100;
  return {
    nodes: [...placed.values()],
    links: links.map((l) => {
      const from = placed.get(l.source)!;
      const to = placed.get(l.target)!;
      const x0 = from.x + nodeWidth;
      const x1 = to.x;
      const mid = (x0 + x1) / 2;
      const y0 = sourceY.get(l)!;
      const y1 = targetY.get(l)!;
      return {
        source: l.source,
        target: l.target,
        value: l.value,
        path: `M${round(x0)},${round(y0)}C${round(mid)},${round(y0)} ${round(mid)},${round(y1)} ${round(x1)},${round(y1)}`,
        width: Math.max(round(l.value * scale), 0.5),
        color: from.color,
      };
    }),
  };
}
