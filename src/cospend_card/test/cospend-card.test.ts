import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import "../src/cospend-card";
import type { BillItem, HassLike, Project } from "../src/types";

type Card = HTMLElement & {
  hass?: HassLike;
  setConfig(config: Record<string, unknown>): void;
  getCardSize(): number;
  updateComplete: Promise<boolean>;
};

const members = [
  { id: 1, name: "Alice", activated: true, weight: 1, color: "#336699", balance: 40 },
  { id: 2, name: "Bob", activated: true, weight: 1, color: null, balance: -40 },
];

function project(overrides: Partial<Project> = {}): Project {
  return {
    entry_id: "e1",
    id: "voyage",
    name: "Voyage",
    currency: "EUR",
    archived: false,
    can_write: true,
    access_level: 4,
    total_spent: 100,
    nb_bills: 2,
    pending: 0,
    available: true,
    members,
    categories: [{ id: 1, name: "Courses", icon: "🛒", color: "#fa0" }],
    payment_modes: [],
    currencies: [],
    ...overrides,
  };
}

function bill(id: number, what: string, extra: Partial<BillItem> = {}): BillItem {
  return {
    ids: [id],
    id,
    is_group: false,
    what,
    amount: 80,
    date: "2026-11-15",
    timestamp: 1000 + id,
    payer_id: 1,
    ower_ids: [1, 2],
    category_id: 1,
    payment_mode_id: 0,
    comment: "",
    repeat: "n",
    foreign: null,
    pending: false,
    ...extra,
  };
}

function makeHass(projects: Project[], bills: BillItem[], onWrite?: (m: Record<string, unknown>) => unknown) {
  const calls: Array<Record<string, unknown>> = [];
  let notify: () => void = () => {};
  const hass: HassLike = {
    language: "fr",
    async callWS<T>(message: Record<string, unknown>): Promise<T> {
      calls.push(message);
      switch (message.type) {
        case "cospend/projects":
          return { projects } as T;
        case "cospend/bills": {
          const search = String(message.search ?? "").toLowerCase();
          const items = bills.filter((b) => b.what.toLowerCase().includes(search));
          const offset = Number(message.offset);
          const limit = Number(message.limit);
          return {
            total: items.length,
            offset,
            has_more: offset + limit < items.length,
            items: items.slice(offset, offset + limit),
          } as T;
        }
        case "cospend/settlement":
          return {
            source: "server",
            transactions: [{ from_id: 2, to_id: 1, amount: 40 }],
            pending: 0,
          } as T;
        case "cospend/bill": {
          const found = bills.find((b) => b.id === message.bill_id)!;
          return {
            ...found,
            shares: [
              { member_id: 1, name: "Alice", amount: 40 },
              { member_id: 2, name: "Bob", amount: 40 },
            ],
          } as T;
        }
      }
      if (message.type === "call_service" && onWrite) {
        return { response: await onWrite(message) } as T;
      }
      throw new Error(`inattendu : ${String(message.type)}`);
    },
    connection: {
      async subscribeMessage(callback: (message: never) => void) {
        notify = () => callback(undefined as never);
        return () => {};
      },
    },
  };
  return { hass, calls, fire: () => notify() };
}

async function mount(hass: HassLike, config: Record<string, unknown> = {}): Promise<Card> {
  const card = document.createElement("cospend-card") as Card;
  card.setConfig({ type: "custom:cospend-card", ...config });
  card.hass = hass;
  document.body.append(card);
  await settle(card);
  return card;
}

async function settle(card: Card): Promise<void> {
  for (let i = 0; i < 6; i++) {
    await Promise.resolve();
    await card.updateComplete;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

const text = (card: Card) => card.shadowRoot!.textContent!.replace(/\s+/g, " ");

describe("cospend-card", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("est enregistrée et déclarée", () => {
    expect(customElements.get("cospend-card")).toBeDefined();
    expect(window.customCards?.some((card) => card.type === "cospend-card")).toBe(true);
    expect(customElements.get("cospend-card-editor")).toBeDefined();
  });

  it("affiche les soldes et les dépenses du projet", async () => {
    const { hass } = makeHass([project()], [bill(1, "Courses"), bill(2, "Essence")]);
    const card = await mount(hass);
    const content = text(card);
    expect(content).toContain("Voyage");
    expect(content).toContain("Alice");
    expect(content).toContain("Bob");
    expect(content).toMatch(/\+40,00\s*€/);
    expect(content).toMatch(/-40,00\s*€/);
    expect(content).toContain("Courses");
    expect(content).toContain("Essence");
    expect(content).toContain("Payé par Alice");
    expect(content).toContain("Pour tout le monde");
  });

  it("affiche l'icône de la catégorie, 💰 pour un remboursement et rien sans catégorie", async () => {
    const { hass } = makeHass(
      [project()],
      [
        bill(1, "Courses", { category_id: 1 }),
        bill(2, "A → B", { category_id: -11 }),
        bill(3, "Sans catégorie", { category_id: 0 }),
      ],
    );
    const card = await mount(hass);
    const icons = Array.from(card.shadowRoot!.querySelectorAll(".row .icon")).map((el) =>
      el.textContent!.trim(),
    );
    expect(icons).toEqual(["🛒", "💰", ""]);
    expect(card.shadowRoot!.querySelectorAll(".row .icon ha-icon")).toHaveLength(1);
  });

  it("masque le sélecteur quand le projet est fixé et le propose sinon", async () => {
    const other = project({ id: "maison", name: "Maison" });
    const { hass } = makeHass([project(), other], []);
    expect(
      (await mount(hass)).shadowRoot!.querySelector(".project-select"),
    ).not.toBeNull();
    document.body.innerHTML = "";
    const fixed = await mount(hass, { project: "maison" });
    expect(fixed.shadowRoot!.querySelector(".project-select")).toBeNull();
    expect(text(fixed)).toContain("Maison");
  });

  it("n'affiche pas les projets archivés sauf s'ils sont choisis", async () => {
    const archived = project({ id: "vieux", name: "Vieux", archived: true });
    const { hass } = makeHass([archived, project()], []);
    const card = await mount(hass);
    expect(text(card)).not.toContain("Vieux");
    document.body.innerHTML = "";
    const chosen = await mount(hass, { project: "vieux" });
    expect(text(chosen)).toContain("archivé");
  });

  it("respecte les blocs masqués", async () => {
    const { hass, calls } = makeHass([project()], [bill(1, "Courses")]);
    const card = await mount(hass, { show_bills: false, show_balances: true });
    expect(text(card)).toContain("Alice");
    expect(text(card)).not.toContain("Rechercher");
    expect(calls.some((c) => c.type === "cospend/bills")).toBe(false);
  });

  it("pagine avec « Afficher plus »", async () => {
    const bills = Array.from({ length: 5 }, (_, i) => bill(i + 1, `Dépense ${i + 1}`));
    const { hass, calls } = makeHass([project()], bills);
    const card = await mount(hass, { page_size: 2 });
    expect(card.shadowRoot!.querySelectorAll(".row")).toHaveLength(2);
    (card.shadowRoot!.querySelector(".more") as HTMLButtonElement).click();
    await settle(card);
    expect(card.shadowRoot!.querySelectorAll(".row")).toHaveLength(4);
    const last = calls.filter((c) => c.type === "cospend/bills").at(-1)!;
    expect(last.offset).toBe(2);
  });

  it("cherche côté serveur après un court délai", async () => {
    const { hass, calls } = makeHass([project()], [bill(1, "Courses"), bill(2, "Essence")]);
    const card = await mount(hass);
    vi.useFakeTimers();
    const input = card.shadowRoot!.querySelector(".search") as HTMLInputElement;
    input.value = "ess";
    input.dispatchEvent(new Event("input"));
    await vi.advanceTimersByTimeAsync(400);
    vi.useRealTimers();
    await settle(card);
    expect(calls.filter((c) => c.type === "cospend/bills").at(-1)!.search).toBe("ess");
    expect(card.shadowRoot!.querySelectorAll(".row")).toHaveLength(1);
  });

  it("ouvre le détail avec les parts, puis revient à la liste", async () => {
    const { hass } = makeHass([project()], [bill(1, "Courses", { comment: "du pain" })]);
    const card = await mount(hass);
    (card.shadowRoot!.querySelector(".row") as HTMLButtonElement).click();
    await settle(card);
    const content = text(card);
    expect(content).toContain("du pain");
    expect(content).toContain("Parts");
    expect(card.shadowRoot!.querySelectorAll(".balances li")).toBeTruthy();
    (card.shadowRoot!.querySelector(".back") as HTMLButtonElement).click();
    await settle(card);
    expect(card.shadowRoot!.querySelector(".detail")).toBeNull();
  });

  it("signale les opérations en attente et le serveur injoignable", async () => {
    const { hass } = makeHass([project({ pending: 2, available: false })], []);
    const card = await mount(hass);
    expect(text(card)).toContain("2 en attente");
    expect(text(card)).toContain("injoignable");
    expect(text(card)).toContain("Aucune dépense");
  });

  it("indique l'absence de projet", async () => {
    const { hass } = makeHass([], []);
    expect(text(await mount(hass))).toContain("Aucun projet Cospend");
  });

  it("propose de réessayer en cas d'erreur", async () => {
    const { hass } = makeHass([], []);
    hass.callWS = async () => {
      throw new Error("boum");
    };
    const card = await mount(hass);
    expect(text(card)).toContain("Impossible de lire");
    expect(card.shadowRoot!.querySelector("button.link")).not.toBeNull();
  });

  it("se met à jour quand l'intégration signale un changement", async () => {
    const bills = [bill(1, "Courses")];
    const { hass, calls, fire } = makeHass([project()], bills);
    const card = await mount(hass);
    expect(card.shadowRoot!.querySelectorAll(".row")).toHaveLength(1);
    bills.push(bill(2, "Essence"));
    const before = calls.length;
    fire();
    await new Promise((resolve) => setTimeout(resolve, 700));
    await settle(card);
    expect(calls.length).toBeGreaterThan(before);
    expect(card.shadowRoot!.querySelectorAll(".row")).toHaveLength(2);
  });
});

describe("écriture", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  const click = (card: Card, selector: string) =>
    (card.shadowRoot!.querySelector(selector) as HTMLButtonElement).click();

  it("propose l'ajout seulement si le projet est modifiable et l'écriture autorisée", async () => {
    const { hass } = makeHass([project()], []);
    expect((await mount(hass)).shadowRoot!.querySelector("button.add")).not.toBeNull();
    document.body.innerHTML = "";
    expect((await mount(hass, { allow_write: false })).shadowRoot!.querySelector("button.add")).toBeNull();
    document.body.innerHTML = "";
    const readOnly = makeHass([project({ can_write: false })], []);
    expect((await mount(readOnly.hass)).shadowRoot!.querySelector("button.add")).toBeNull();
  });

  it("ouvre le formulaire puis revient à la liste en annulant", async () => {
    const { hass } = makeHass([project()], []);
    const card = await mount(hass);
    click(card, "button.add");
    await settle(card);
    expect(card.shadowRoot!.querySelector("cospend-bill-form")).not.toBeNull();
    card.shadowRoot!.querySelector("cospend-bill-form")!.dispatchEvent(new CustomEvent("cancel"));
    await settle(card);
    expect(card.shadowRoot!.querySelector("cospend-bill-form")).toBeNull();
  });

  it("confirme l'enregistrement, y compris hors ligne, et recharge la liste", async () => {
    const { hass, calls } = makeHass([project()], [bill(1, "Courses")]);
    const card = await mount(hass);
    click(card, "button.add");
    await settle(card);
    const form = card.shadowRoot!.querySelector("cospend-bill-form")!;
    form.dispatchEvent(new CustomEvent("saved", { detail: { queued: true } }));
    await settle(card);
    expect(card.shadowRoot!.querySelector("cospend-bill-form")).toBeNull();
    expect(text(card)).toContain("Enregistrée hors ligne");
    const refreshed = calls.filter((c) => c.type === "cospend/bills").length;
    expect(refreshed).toBeGreaterThan(1);
  });

  it("demande confirmation avant de supprimer, puis supprime", async () => {
    const writes: Array<Record<string, unknown>> = [];
    const { hass } = makeHass([project()], [bill(1, "Courses")], (message) => {
      writes.push(message);
      return {};
    });
    const card = await mount(hass);
    click(card, ".row");
    await settle(card);
    click(card, "button.danger");
    await settle(card);
    expect(writes).toHaveLength(0); // rien n'est parti avant la confirmation
    expect(text(card)).toContain("corbeille de Nextcloud");
    click(card, "button.danger.solid");
    await settle(card);
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({
      service: "delete_bill",
      service_data: { project: "voyage", bill_id: 1, whole_group: true },
    });
    expect(card.shadowRoot!.querySelector(".detail")).toBeNull();
    expect(text(card)).toContain("Dépense supprimée");
  });

  it("modifie une dépense depuis son détail et revient au détail à jour", async () => {
    const writes: Array<Record<string, unknown>> = [];
    const { hass } = makeHass([project()], [bill(1, "Courses")], (message) => {
      writes.push(message);
      return { bill_ids: [1] };
    });
    const card = await mount(hass);
    click(card, ".row");
    await settle(card);
    click(card, ".detail-actions .secondary");
    await settle(card);
    const form = card.shadowRoot!.querySelector("cospend-bill-form")!;
    expect(form.shadowRoot!.querySelector("h2")!.textContent).toContain("Modifier");
    form.dispatchEvent(new CustomEvent("saved", { detail: { edited: true, queued: false } }));
    await settle(card);
    expect(card.shadowRoot!.querySelector("cospend-bill-form")).toBeNull();
    expect(card.shadowRoot!.querySelector(".detail")).not.toBeNull(); // retour au détail
    expect(text(card)).toContain("Dépense modifiée");
  });

  it("annule la modification et retrouve le détail", async () => {
    const { hass } = makeHass([project()], [bill(1, "Courses")]);
    const card = await mount(hass);
    click(card, ".row");
    await settle(card);
    click(card, ".detail-actions .secondary");
    await settle(card);
    card.shadowRoot!.querySelector("cospend-bill-form")!.dispatchEvent(new CustomEvent("cancel"));
    await settle(card);
    expect(card.shadowRoot!.querySelector(".detail")).not.toBeNull();
    // un ajout ouvert ensuite est bien un formulaire vierge
    click(card, ".back");
    await settle(card);
    click(card, "button.add");
    await settle(card);
    expect(
      card.shadowRoot!.querySelector("cospend-bill-form")!.shadowRoot!.querySelector("h2")!.textContent,
    ).toContain("Nouvelle");
  });

  it("annule la suppression", async () => {
    const writes: unknown[] = [];
    const { hass } = makeHass([project()], [bill(1, "Courses")], (m) => writes.push(m));
    const card = await mount(hass);
    click(card, ".row");
    await settle(card);
    click(card, "button.danger");
    await settle(card);
    click(card, ".confirm button.secondary");
    await settle(card);
    expect(writes).toHaveLength(0);
    expect(card.shadowRoot!.querySelector(".confirm")).toBeNull();
  });

  it("affiche l'erreur si la suppression échoue", async () => {
    const { hass } = makeHass([project()], [bill(1, "Courses")], () => {
      throw { message: "Projet archivé" };
    });
    const card = await mount(hass);
    click(card, ".row");
    await settle(card);
    click(card, "button.danger");
    await settle(card);
    click(card, "button.danger.solid");
    await settle(card);
    expect(text(card)).toContain("Projet archivé");
  });

  it("n'offre pas la suppression en lecture seule", async () => {
    const { hass } = makeHass([project()], [bill(1, "Courses")]);
    const card = await mount(hass, { allow_write: false });
    click(card, ".row");
    await settle(card);
    expect(card.shadowRoot!.querySelector("button.danger")).toBeNull();
  });
});

describe("gestion du projet", () => {
  const click = (card: Card, selector: string) =>
    (card.shadowRoot!.querySelector(selector) as HTMLElement).click();
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  const as = (hass: HassLike, isAdmin: boolean): HassLike => ({
    ...hass,
    user: { name: "Quentin", is_admin: isAdmin },
  });
  const gear = (card: Card) => card.shadowRoot!.querySelector("button.gear.manage");

  it("réserve la roue aux administrateurs tant que l'option n'est pas cochée", async () => {
    const { hass } = makeHass([project()], []);
    expect(gear(await mount(as(hass, true)))).not.toBeNull();
    document.body.innerHTML = "";
    expect(gear(await mount(as(hass, false)))).toBeNull();
    document.body.innerHTML = "";
    expect(gear(await mount(as(hass, false), { allow_manage: false }))).toBeNull();
  });

  it("ouvre la roue à tous les utilisateurs quand l'option est cochée", async () => {
    const { hass } = makeHass([project()], []);
    expect(gear(await mount(as(hass, false), { allow_manage: true }))).not.toBeNull();
  });

  it("exige toujours le niveau gestionnaire et l'écriture autorisée", async () => {
    const low = makeHass([project({ access_level: 2 })], []);
    expect(gear(await mount(as(low.hass, true), { allow_manage: true }))).toBeNull();
    document.body.innerHTML = "";
    const ok = makeHass([project()], []);
    expect(gear(await mount(as(ok.hass, true), { allow_write: false }))).toBeNull();
    document.body.innerHTML = "";
    expect(gear(await mount(as(ok.hass, true), { allow_manage: true, allow_write: false }))).toBeNull();
  });

  it("ouvre l'écran de gestion, annonce la modification puis le ferme", async () => {
    const { hass } = makeHass([project()], []);
    const card = await mount(as(hass, true));
    click(card, "button.gear.manage");
    await settle(card);
    const manage = card.shadowRoot!.querySelector("cospend-manage")!;
    expect(manage).not.toBeNull();
    expect(card.shadowRoot!.querySelector("button.gear.manage")).toBeNull();
    manage.dispatchEvent(new CustomEvent("changed", { detail: { text: "Ajouté" } }));
    await settle(card);
    expect(text(card)).toContain("Ajouté");
    manage.dispatchEvent(new CustomEvent("close"));
    await settle(card);
    expect(card.shadowRoot!.querySelector("cospend-manage")).toBeNull();
  });
});

describe("remboursements", () => {
  const click = (card: Card, selector: string) =>
    (card.shadowRoot!.querySelector(selector) as HTMLElement).click();
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("ouvre l'écran des remboursements puis revient à la liste", async () => {
    const { hass } = makeHass([project()], []);
    const card = await mount(hass);
    click(card, "button.settle");
    await settle(card);
    expect(card.shadowRoot!.querySelector("cospend-settlement")).not.toBeNull();
    expect(card.shadowRoot!.querySelector("button.settle")).toBeNull();
    card.shadowRoot!.querySelector("cospend-settlement")!.dispatchEvent(new CustomEvent("close"));
    await settle(card);
    expect(card.shadowRoot!.querySelector("cospend-settlement")).toBeNull();
  });

  it("annonce l'enregistrement d'un remboursement", async () => {
    const { hass } = makeHass([project()], []);
    const card = await mount(hass);
    click(card, "button.settle");
    await settle(card);
    card.shadowRoot!
      .querySelector("cospend-settlement")!
      .dispatchEvent(new CustomEvent("changed", { detail: { text: "Remboursement enregistré" } }));
    await settle(card);
    expect(text(card)).toContain("Remboursement enregistré");
  });

  it("masque le bouton avec show_settlement: false", async () => {
    const { hass } = makeHass([project()], []);
    const card = await mount(hass, { show_settlement: false });
    expect(card.shadowRoot!.querySelector("button.settle")).toBeNull();
  });
});

describe("éditeur", () => {
  it("émet config-changed avec la configuration modifiée", async () => {
    const { hass } = makeHass([project()], []);
    const editor = document.createElement("cospend-card-editor") as HTMLElement & {
      hass?: HassLike;
      setConfig(config: Record<string, unknown>): void;
      updateComplete: Promise<boolean>;
    };
    editor.setConfig({ type: "custom:cospend-card" });
    editor.hass = hass;
    document.body.append(editor);
    await editor.updateComplete;
    await new Promise((resolve) => setTimeout(resolve, 0));
    await editor.updateComplete;

    const received: Array<Record<string, unknown>> = [];
    editor.addEventListener("config-changed", (event) =>
      received.push((event as CustomEvent).detail.config),
    );
    const form = editor.shadowRoot!.querySelector("ha-form")!;
    form.dispatchEvent(
      new CustomEvent("value-changed", {
        detail: {
          value: {
            title: "Notre budget",
            project: "voyage",
            show_balances: true,
            show_bills: false,
            show_search: true,
            page_size: 10,
          },
        },
      }),
    );
    expect(received[0]).toMatchObject({
      type: "custom:cospend-card",
      title: "Notre budget",
      project: "voyage",
      entry_id: "e1",
      show_bills: false,
      page_size: 10,
    });
    const schema = (form as unknown as { schema: Array<{ name: string; selector: any }> }).schema;
    const options = schema.find((item) => item.name === "project")!.selector.select.options;
    expect(options.map((option: { value: string }) => option.value)).toEqual(["", "voyage"]);
  });
});
