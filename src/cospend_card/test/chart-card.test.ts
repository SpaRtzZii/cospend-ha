import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../src/chart-card";
import type { HassLike, Project, Statistics } from "../src/types";

const project = (extra: Partial<Project> = {}): Project =>
  ({
    entry_id: "e1",
    id: "voyage",
    name: "Voyage",
    currency: "EUR",
    archived: false,
    can_write: true,
    access_level: 4,
    total_spent: 100,
    nb_bills: 3,
    pending: 0,
    available: true,
    members: [
      { id: 1, name: "Alice", activated: true, weight: 1, color: "#336699", balance: 20 },
      { id: 2, name: "Bob", activated: true, weight: 1, color: null, balance: -20 },
    ],
    categories: [
      { id: 5, name: "Courses", icon: "🛒", color: "#e15759" },
      { id: 6, name: "Resto", icon: "🍴", color: "" },
    ],
    payment_modes: [],
    currencies: [],
    ...extra,
  }) as Project;

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
  payment_modes: [],
  months: [
    { month: "2026-10", total: 40, by_category: { "5": 30, "6": 10 } },
    { month: "2026-11", total: 60, by_category: { "5": 45, "6": 15 } },
  ],
  links: [
    { source: "payer:1", target: "category:5", value: 75 },
    { source: "payer:2", target: "category:6", value: 25 },
    { source: "category:5", target: "ower:1", value: 75 },
    { source: "category:6", target: "ower:2", value: 25 },
  ],
  pending: 0,
  ...extra,
});

type ChartCard = HTMLElement & {
  hass?: HassLike;
  setConfig(config: Record<string, unknown>): void;
  getCardSize(): number;
  updateComplete: Promise<boolean>;
};

interface Setup {
  projects?: Project[];
  answer?: Statistics | Error;
}

function makeHass(setup: Setup = {}) {
  const calls: Array<Record<string, unknown>> = [];
  let notify: () => void = () => {};
  const hass = {
    language: "fr",
    async callWS(message: Record<string, unknown>) {
      calls.push(message);
      if (message.type === "cospend/projects") return { projects: setup.projects ?? [project()] };
      if (message.type === "cospend/statistics") {
        if (setup.answer instanceof Error) throw setup.answer;
        return setup.answer ?? stats();
      }
      throw new Error(`inattendu : ${String(message.type)}`);
    },
    connection: {
      async subscribeMessage(callback: (message: never) => void) {
        notify = () => callback(undefined as never);
        return () => {};
      },
    },
  } as unknown as HassLike;
  return { hass, calls, fire: () => notify() };
}

async function flush(card: ChartCard) {
  for (let i = 0; i < 6; i++) {
    await Promise.resolve();
    await card.updateComplete;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

async function mount(hass: HassLike, config: Record<string, unknown> = {}): Promise<ChartCard> {
  const card = document.createElement("cospend-chart-card") as ChartCard;
  card.setConfig({ type: "custom:cospend-chart-card", ...config });
  card.hass = hass;
  document.body.append(card);
  await flush(card);
  return card;
}

const root = (card: ChartCard) => card.shadowRoot!;
const text = (card: ChartCard) => root(card).textContent!.replace(/\s+/g, " ");
const statCalls = (calls: Array<Record<string, unknown>>) =>
  calls.filter((c) => c.type === "cospend/statistics");

describe("cospend-chart-card", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("affiche par défaut les dépenses par mois du mois en cours", async () => {
    const { hass, calls } = makeHass();
    const card = await mount(hass);
    const [call] = statCalls(calls);
    expect(call).toMatchObject({ project_id: "voyage", entry_id: "e1" });
    expect(String(call.date_from)).toMatch(/^\d{4}-\d{2}-01$/);
    expect(call.date_to).toBeDefined();
    expect(root(card).querySelector("svg.months")).not.toBeNull();
    expect([...root(card).querySelectorAll("ul.legend li")].map((li) => li.textContent!.trim())).toEqual(
      ["Courses", "Resto"],
    );
    expect(text(card)).toContain("Dépenses par mois");
    expect(text(card)).toContain("Voyage");
    expect(text(card)).toContain("Ce mois-ci");
    expect(root(card).querySelector(".total")!.textContent).toMatch(/100,00\s*€/);
    expect(text(card)).toContain("3 dépense(s)");
  });

  it("affiche chaque type de graphique", async () => {
    const check = async (chart: string, selector: string) => {
      document.body.innerHTML = "";
      const { hass } = makeHass();
      const card = await mount(hass, { chart });
      expect(root(card).querySelector(selector), chart).not.toBeNull();
    };
    await check("categories", "ul.bars:not(.members) li");
    await check("members", "ul.bars.members li");
    await check("flows", "svg.sankey path");
  });

  it("les soldes n'interrogent pas les statistiques", async () => {
    const { hass, calls } = makeHass();
    const card = await mount(hass, { chart: "balances" });
    expect(statCalls(calls)).toHaveLength(0);
    const balances = root(card).querySelector("cospend-balances") as HTMLElement;
    expect(balances.shadowRoot!.textContent).toContain("Alice");
    expect(root(card).querySelector(".chip")).toBeNull();
  });

  it("transmet la période et les filtres", async () => {
    const { hass, calls } = makeHass();
    await mount(hass, {
      period: "year",
      payer: 2,
      category: 0,
      include_reimbursements: true,
    });
    const [call] = statCalls(calls);
    expect(String(call.date_from)).toMatch(/^\d{4}-01-01$/);
    expect(String(call.date_to)).toMatch(/^\d{4}-12-31$/);
    expect(call).toMatchObject({ payer_id: 2, category_id: 0, include_reimbursements: true });
  });

  it("n'envoie pas de dates pour « toute la période »", async () => {
    const { hass, calls } = makeHass();
    await mount(hass, { period: "all" });
    const [call] = statCalls(calls);
    expect(call).not.toHaveProperty("date_from");
    expect(call).not.toHaveProperty("date_to");
    expect(call).not.toHaveProperty("payer_id");
  });

  it("respecte le titre et le masquage du total", async () => {
    const { hass } = makeHass();
    const card = await mount(hass, { title: "Budget courses", show_total: false });
    expect(root(card).querySelector(".title")!.textContent).toBe("Budget courses");
    expect(root(card).querySelector(".subtitle")).toBeNull();
    expect(root(card).querySelector(".summary")).toBeNull();
  });

  it("indique quand aucune dépense ne correspond", async () => {
    const { hass } = makeHass({ answer: stats({ total: 0, count: 0, months: [], links: [] }) });
    const card = await mount(hass);
    expect(text(card)).toContain("Aucune dépense ne correspond");
    expect(root(card).querySelector("svg")).toBeNull();
  });

  it("affiche l'erreur et permet de réessayer", async () => {
    const { hass, calls } = makeHass({ projects: [], answer: new Error("hors ligne") });
    const card = await mount(hass);
    expect(text(card)).toContain("Aucun projet Cospend");
    // Une erreur réseau sur la liste des projets : message et bouton « Réessayer ».
    document.body.innerHTML = "";
    const failing = {
      language: "fr",
      callWS: async () => {
        throw new Error("hors ligne");
      },
      connection: { subscribeMessage: async () => () => {} },
    } as unknown as HassLike;
    const broken = await mount(failing);
    expect(root(broken).querySelector(".error")!.textContent).toContain("hors ligne");
    expect(root(broken).querySelector("button.retry")).not.toBeNull();
    expect(calls.length).toBeGreaterThan(0);
  });

  it("choisit le projet configuré, ignore les archivés sinon", async () => {
    const projects = [
      project({ id: "vieux", name: "Vieux", archived: true }),
      project({ id: "voyage", name: "Voyage" }),
    ];
    const first = await mount(makeHass({ projects }).hass);
    expect(text(first)).toContain("Voyage");
    expect(text(first)).not.toContain("Vieux");
    document.body.innerHTML = "";
    const chosen = await mount(makeHass({ projects }).hass, { project: "vieux" });
    expect(text(chosen)).toContain("Vieux");
    document.body.innerHTML = "";
    const unknown = await mount(makeHass({ projects }).hass, { project: "absent" });
    expect(text(unknown)).toContain("Aucun projet Cospend");
  });

  it("se met à jour quand l'intégration signale un changement", async () => {
    const { hass, calls, fire } = makeHass();
    const card = await mount(hass);
    const before = statCalls(calls).length;
    vi.useFakeTimers();
    fire();
    await vi.advanceTimersByTimeAsync(700);
    vi.useRealTimers();
    await flush(card);
    expect(statCalls(calls).length).toBeGreaterThan(before);
  });

  it("recharge quand la configuration change", async () => {
    const { hass, calls } = makeHass();
    const card = await mount(hass);
    card.setConfig({ type: "custom:cospend-chart-card", period: "all" });
    await flush(card);
    expect(statCalls(calls).at(-1)).not.toHaveProperty("date_from");
  });

  it("refuse un type de graphique inconnu et annonce sa taille", async () => {
    const { hass } = makeHass();
    const card = await mount(hass);
    expect(() => card.setConfig({ type: "x", chart: "camembert" })).toThrow();
    expect(card.getCardSize()).toBeGreaterThan(0);
  });
});

describe("cospend-chart-card-editor", () => {
  type Editor = HTMLElement & {
    hass?: HassLike;
    setConfig(config: Record<string, unknown>): void;
    updateComplete: Promise<boolean>;
  };

  async function mountEditor(config: Record<string, unknown>): Promise<Editor> {
    const editor = document.createElement("cospend-chart-card-editor") as Editor;
    editor.setConfig(config);
    editor.hass = makeHass().hass;
    document.body.append(editor);
    await editor.updateComplete;
    await new Promise((resolve) => setTimeout(resolve, 0));
    await editor.updateComplete;
    return editor;
  }

  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("propose les graphiques, les périodes, les membres et les catégories du projet", async () => {
    const editor = await mountEditor({ type: "custom:cospend-chart-card" });
    const form = editor.shadowRoot!.querySelector("ha-form") as unknown as {
      schema: Array<{ name: string; selector: any }>;
    };
    const values = (name: string) =>
      form.schema
        .find((item) => item.name === name)!
        .selector.select.options.map((o: { value: string }) => o.value);
    expect(values("chart")).toEqual(["months", "categories", "members", "flows", "balances"]);
    expect(values("period")).toEqual(["month", "last_month", "last_30", "year", "all"]);
    expect(values("payer")).toEqual(["", "1", "2"]);
    expect(values("category")).toEqual(["", "0", "5", "6"]);
  });

  it("émet config-changed avec des identifiants numériques", async () => {
    const editor = await mountEditor({ type: "custom:cospend-chart-card" });
    const received: Array<Record<string, unknown>> = [];
    editor.addEventListener("config-changed", (event) =>
      received.push((event as CustomEvent).detail.config),
    );
    const form = editor.shadowRoot!.querySelector("ha-form")!;
    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: {
          value: {
            title: "",
            project: "voyage",
            chart: "flows",
            period: "last_30",
            payer: "2",
            category: "0",
            include_reimbursements: true,
            show_total: false,
          },
        },
      }),
    );
    expect(received[0]).toMatchObject({
      type: "custom:cospend-chart-card",
      project: "voyage",
      entry_id: "e1",
      chart: "flows",
      period: "last_30",
      payer: 2,
      category: 0,
      include_reimbursements: true,
      show_total: false,
    });
    expect(received[0]).not.toHaveProperty("title");
    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: { value: { chart: "months", period: "month", payer: "", category: "" } },
      }),
    );
    expect(received[1]).not.toHaveProperty("payer");
    expect(received[1]).not.toHaveProperty("category");
  });
});
