import { beforeEach, describe, expect, it } from "vitest";

import "../src/stats";
import type { HassLike, Project, Statistics } from "../src/types";

const project = {
  entry_id: "e1",
  id: "voyage",
  name: "Voyage",
  currency: "EUR",
  members: [
    {
      id: 1,
      name: "Alice",
      activated: true,
      weight: 1,
      color: "#336699",
      balance: 20,
    },
    {
      id: 2,
      name: "Bob",
      activated: true,
      weight: 1,
      color: null,
      balance: -20,
    },
  ],
  categories: [
    { id: 5, name: "Courses", icon: "🛒", color: "#e15759" },
    { id: 6, name: "Resto", icon: "🍴", color: "" },
  ],
  payment_modes: [{ id: 2, name: "Carte", icon: "💳", color: "" }],
} as unknown as Project;

const stats = (extra: Partial<Statistics> = {}): Statistics => ({
  total: 100,
  count: 3,
  members: [
    { id: 1, paid: 70, spent: 50, balance: 20 },
    { id: 2, paid: 30, spent: 50, balance: -20 },
  ],
  categories: [
    { id: 5, total: 75 },
    { id: 6, total: 25 },
  ],
  payment_modes: [{ id: 2, total: 100 }],
  months: [
    { month: "2026-10", total: 40, by_category: { "5": 30, "6": 10 } },
    { month: "2026-11", total: 60, by_category: { "5": 45, "6": 15 } },
  ],
  links: [
    { source: "payer:1", target: "category:5", value: 75 },
    { source: "payer:2", target: "category:6", value: 25 },
    { source: "category:5", target: "ower:1", value: 40 },
    { source: "category:5", target: "ower:2", value: 35 },
    { source: "category:6", target: "ower:2", value: 25 },
  ],
  pending: 0,
  ...extra,
});

type Stats = HTMLElement & {
  hass?: HassLike;
  project?: Project;
  updateComplete: Promise<boolean>;
};

async function mount(
  answer: Statistics | Error,
  calls: Array<Record<string, unknown>> = [],
) {
  const element = document.createElement("cospend-stats") as Stats;
  element.hass = {
    language: "fr",
    callWS: async (message: Record<string, unknown>) => {
      calls.push(message);
      if (answer instanceof Error) throw answer;
      return answer as never;
    },
    connection: {} as never,
  } as HassLike;
  element.project = project;
  document.body.append(element);
  await flush(element);
  return element;
}

async function flush(element: Stats) {
  for (let i = 0; i < 3; i++) {
    await element.updateComplete;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

const root = (element: Stats) => element.shadowRoot!;
const text = (element: Stats) =>
  root(element).textContent!.replace(/\s+/g, " ");
const click = async (element: Stats, selector: string) => {
  (root(element).querySelector(selector) as HTMLElement).click();
  await flush(element);
};
const choose = async (element: Stats, selector: string, value: string) => {
  const field = root(element).querySelector(selector) as
    HTMLSelectElement | HTMLInputElement;
  field.value = value;
  field.dispatchEvent(new Event("change"));
  await flush(element);
};

describe("cospend-stats", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("demande les statistiques sans filtre et affiche total et nombre", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(stats(), calls);
    expect(calls[0]).toMatchObject({
      type: "cospend/statistics",
      project_id: "voyage",
      entry_id: "e1",
    });
    expect(calls[0]).not.toHaveProperty("date_from");
    expect(root(element).querySelector(".total")!.textContent).toMatch(
      /100,00\s*€/,
    );
    expect(root(element).querySelector(".count")!.textContent).toBe("3");
  });

  it("montre le tableau par membre, catégorie, mode et mois", async () => {
    const element = await mount(stats());
    const t = text(element);
    expect(t).toMatch(/Alice 70,00\s*€ 50,00\s*€ \+20,00\s*€/);
    expect(t).toMatch(/Courses 75,00\s*€ 75 %/);
    expect(t).toMatch(/Resto 25,00\s*€ 25 %/);
    expect(t).toContain("Carte");
    expect(t).toMatch(/oct\.? 2026/i);
  });

  it("montre les graphiques : colonnes par mois et barres par catégorie", async () => {
    const element = await mount(stats());
    await click(element, '[data-tab="chart"]');
    expect(root(element).querySelectorAll("svg.months g")).toHaveLength(2);
    expect(root(element).querySelectorAll("ul.bars li")).toHaveLength(2);
  });

  it("montre le diagramme de Sankey avec un flux par lien", async () => {
    const element = await mount(stats());
    await click(element, '[data-tab="sankey"]');
    expect(root(element).querySelectorAll("svg.sankey path")).toHaveLength(5);
    expect(root(element).querySelector("svg.sankey")!.textContent).toContain(
      "Courses",
    );
  });

  it("n'écrit pas le libellé des nœuds trop fins du Sankey, mais garde leur infobulle", async () => {
    const element = await mount(
      stats({
        links: [
          { source: "payer:1", target: "category:5", value: 1000 },
          { source: "payer:2", target: "category:6", value: 0.5 },
          { source: "category:5", target: "ower:1", value: 1000 },
          { source: "category:6", target: "ower:2", value: 0.5 },
        ],
      }),
    );
    await click(element, '[data-tab="sankey"]');
    const labels = [...root(element).querySelectorAll("svg.sankey text")].map((n) => n.textContent);
    expect(labels).toContain("Courses");
    expect(labels).not.toContain("Resto");
    expect(root(element).querySelector("svg.sankey")!.innerHTML).toContain("Resto");
  });

  it("envoie les filtres choisis et recharge", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(stats(), calls);
    await click(element, "button.toggle");
    await choose(element, 'select[name="payer"]', "2");
    await choose(element, 'select[name="category"]', "0");
    await choose(element, 'select[name="mode"]', "2");
    await choose(element, 'select[name="period"]', "year");
    const last = calls[calls.length - 1];
    expect(last).toMatchObject({
      payer_id: 2,
      category_id: 0,
      payment_mode_id: 2,
    });
    expect(String(last.date_from)).toMatch(/^\d{4}-01-01$/);
    expect(String(last.date_to)).toMatch(/^\d{4}-12-31$/);
  });

  it("accepte une période personnalisée et les remboursements", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(stats(), calls);
    await click(element, "button.toggle");
    await choose(element, 'select[name="period"]', "custom");
    await choose(element, 'input[name="from"]', "2026-10-01");
    await choose(element, 'input[name="to"]', "2026-10-31");
    const checkbox = root(element).querySelector(
      'input[name="reimbursements"]',
    ) as HTMLInputElement;
    checkbox.checked = true;
    checkbox.dispatchEvent(new Event("change"));
    await flush(element);
    expect(calls[calls.length - 1]).toMatchObject({
      date_from: "2026-10-01",
      date_to: "2026-10-31",
      include_reimbursements: true,
    });
  });

  it("réinitialise les filtres", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(stats(), calls);
    await click(element, "button.toggle");
    await choose(element, 'select[name="payer"]', "1");
    await click(element, "button.reset");
    const last = calls[calls.length - 1];
    expect(last).not.toHaveProperty("payer_id");
    expect(root(element).querySelector("button.reset")).toBeNull();
  });

  it("indique quand aucune dépense ne correspond", async () => {
    const element = await mount(
      stats({ total: 0, count: 0, categories: [], months: [], links: [] }),
    );
    expect(text(element)).toContain("Aucune dépense ne correspond");
    expect(root(element).querySelector("table")).toBeNull();
  });

  it("prévient des opérations en attente", async () => {
    const element = await mount(stats({ pending: 2 }));
    expect(text(element)).toContain("2 opération(s) en attente");
  });

  it("affiche l'erreur du serveur", async () => {
    const element = await mount(new Error("hors ligne"));
    expect(root(element).querySelector(".error")!.textContent).toContain(
      "hors ligne",
    );
  });

  it("émet close au retour", async () => {
    const element = await mount(stats());
    let closed = false;
    element.addEventListener("close", () => (closed = true));
    await click(element, "button.back");
    expect(closed).toBe(true);
  });
});
