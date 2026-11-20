import { describe, expect, it } from "vitest";

import {
  PALETTE,
  categoryColor,
  monthLabel,
  monthName,
  yearShown,
  percent,
  periodRange,
  sankeyLayout,
} from "../src/stats-layout";
import type { SankeyNodeIn } from "../src/stats-layout";
import type { Project, StatsLink } from "../src/types";

describe("periodRange", () => {
  const now = new Date(2026, 10, 20); // 20 novembre 2026

  it("ne borne pas « toute la période »", () => {
    expect(periodRange("all", now)).toEqual({});
    expect(periodRange("custom", now)).toEqual({});
  });

  it("calcule le mois en cours et le mois dernier", () => {
    expect(periodRange("month", now)).toEqual({
      from: "2026-11-01",
      to: "2026-11-30",
    });
    expect(periodRange("last_month", now)).toEqual({
      from: "2026-10-01",
      to: "2026-10-31",
    });
  });

  it("gère le passage d'année pour le mois dernier", () => {
    expect(periodRange("last_month", new Date(2026, 0, 15))).toEqual({
      from: "2025-12-01",
      to: "2025-12-31",
    });
  });

  it("calcule les 30 derniers jours (aujourd'hui compris) et l'année", () => {
    expect(periodRange("last_30", now)).toEqual({
      from: "2026-10-22",
      to: "2026-11-20",
    });
    expect(periodRange("year", now)).toEqual({
      from: "2026-01-01",
      to: "2026-12-31",
    });
  });
});

describe("couleurs et libellés", () => {
  const project = {
    categories: [
      { id: 5, name: "A", icon: "", color: "#112233" },
      { id: 6, name: "B", icon: "", color: "" },
    ],
  } as unknown as Project;

  it("utilise la couleur de la catégorie, sinon la palette", () => {
    expect(categoryColor(project, 5)).toBe("#112233");
    expect(categoryColor(project, 6)).toBe(PALETTE[1]);
    expect(PALETTE).toContain(categoryColor(project, 999));
  });

  it("formate les mois et les pourcentages", () => {
    expect(monthLabel("2026-11", "fr")).toMatch(/nov/i);
    expect(monthLabel("n'importe quoi")).toBe("n'importe quoi");
    expect(monthName("2026-11", "fr")).toMatch(/^nov/i);
    expect(monthName("x")).toBe("x");
    const months = [{ month: "2026-11" }, { month: "2026-12" }, { month: "2027-01" }];
    expect(months.map((_, i) => yearShown(months, i))).toEqual([true, false, true]);
    expect(percent(25, 100)).toBe(25);
    expect(percent(1, 3)).toBe(33);
    expect(percent(5, 0)).toBe(0);
  });
});

describe("sankeyLayout", () => {
  const nodes: SankeyNodeIn[] = [
    { id: "payer:1", label: "A", color: "#111", column: 0 },
    { id: "payer:2", label: "B", color: "#222", column: 0 },
    { id: "category:5", label: "Courses", color: "#333", column: 1 },
    { id: "ower:1", label: "A", color: "#111", column: 2 },
    { id: "ower:2", label: "B", color: "#222", column: 2 },
    { id: "ower:9", label: "Inutilisé", color: "#999", column: 2 },
  ];
  const links: StatsLink[] = [
    { source: "payer:1", target: "category:5", value: 60 },
    { source: "payer:2", target: "category:5", value: 40 },
    { source: "category:5", target: "ower:1", value: 50 },
    { source: "category:5", target: "ower:2", value: 50 },
  ];
  const options = {
    width: 600,
    height: 200,
    margin: 100,
    gap: 10,
    nodeWidth: 12,
  };

  it("ne garde que les nœuds qui ont un flux et les place en colonnes", () => {
    const layout = sankeyLayout(nodes, links, options);
    expect(layout.nodes.map((n) => n.id)).not.toContain("ower:9");
    const x = (id: string) => layout.nodes.find((n) => n.id === id)!.x;
    expect(x("payer:1")).toBe(100);
    expect(x("category:5")).toBeGreaterThan(x("payer:1"));
    expect(x("ower:1")).toBe(600 - 100 - 12);
  });

  it("garde les nœuds dans la hauteur et proportionnels à leur flux", () => {
    const layout = sankeyLayout(nodes, links, options);
    for (const n of layout.nodes) {
      expect(n.y).toBeGreaterThanOrEqual(-0.001);
      expect(n.y + n.height).toBeLessThanOrEqual(200.001);
    }
    const h = (id: string) => layout.nodes.find((n) => n.id === id)!.height;
    expect(h("payer:1") / h("payer:2")).toBeCloseTo(60 / 40);
    expect(h("category:5")).toBeCloseTo(h("payer:1") + h("payer:2"));
  });

  it("réserve une marge en haut et en bas", () => {
    const layout = sankeyLayout(nodes, links, { ...options, padding: 15 });
    for (const n of layout.nodes) {
      expect(n.y).toBeGreaterThanOrEqual(15 - 0.001);
      expect(n.y + n.height).toBeLessThanOrEqual(200 - 15 + 0.001);
    }
  });

  it("trace un flux par lien, d'épaisseur proportionnelle, de la couleur de la source", () => {
    const layout = sankeyLayout(nodes, links, options);
    expect(layout.links).toHaveLength(4);
    const first = layout.links.find((l) => l.source === "payer:1")!;
    const second = layout.links.find((l) => l.source === "payer:2")!;
    expect(first.width / second.width).toBeCloseTo(60 / 40, 1);
    expect(first.color).toBe("#111");
    expect(first.path).toMatch(/^M[\d.]+,[\d.]+C/);
  });

  it("ignore les liens nuls ou vers un nœud inconnu, et gère le vide", () => {
    const layout = sankeyLayout(
      nodes,
      [
        { source: "payer:1", target: "category:5", value: 0 },
        { source: "payer:1", target: "inconnu", value: 10 },
      ],
      options,
    );
    expect(layout).toEqual({ nodes: [], links: [] });
  });
});
