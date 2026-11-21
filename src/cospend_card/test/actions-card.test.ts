import { beforeEach, describe, expect, it } from "vitest";

import "../src/actions-card";
import type { BillItem, HassLike, Project } from "../src/types";

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
    nb_bills: 2,
    pending: 0,
    available: true,
    members: [
      { id: 1, name: "Alice", activated: true, weight: 1, color: null, balance: 10 },
      { id: 2, name: "Bob", activated: true, weight: 1, color: null, balance: -10 },
    ],
    categories: [],
    payment_modes: [],
    currencies: [],
    ...extra,
  }) as Project;

const bill = (id: number, what: string, extra: Partial<BillItem> = {}): BillItem => ({
  ids: [id],
  id,
  is_group: false,
  what,
  amount: 12.5,
  date: "2026-11-10",
  timestamp: 1762732800,
  payer_id: 1,
  ower_ids: [1, 2],
  category_id: 0,
  payment_mode_id: 0,
  comment: "",
  repeat: "n",
  foreign: null,
  pending: false,
  ...extra,
});

type Card = HTMLElement & {
  hass?: HassLike;
  setConfig(config: Record<string, unknown>): void;
  getCardSize(): number;
  updateComplete: Promise<boolean>;
};
type Dialog = HTMLElement & { updateComplete: Promise<boolean> };

function makeHass(projects: Project[] = [project()], bills: BillItem[] = [bill(1, "Pain"), bill(2, "Essence")]) {
  const calls: Array<Record<string, unknown>> = [];
  const hass = {
    language: "fr",
    async callWS(message: Record<string, unknown>) {
      calls.push(message);
      if (message.type === "cospend/projects") return { projects };
      if (message.type === "cospend/bills")
        return { total: bills.length, offset: 0, has_more: false, items: bills };
      if (message.type === "cospend/bill") return bills.find((b) => b.id === message.bill_id);
      if (message.type === "call_service") return { response: {} };
      throw new Error(`inattendu : ${String(message.type)}`);
    },
    connection: { async subscribeMessage() { return () => {}; } },
  } as unknown as HassLike;
  return { hass, calls };
}

const tick = async (n = 6) => {
  for (let i = 0; i < n; i++) {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
};

async function mount(hass: HassLike, config: Record<string, unknown> = {}): Promise<Card> {
  const card = document.createElement("cospend-actions-card") as Card;
  card.setConfig({ type: "custom:cospend-actions-card", ...config });
  card.hass = hass;
  document.body.append(card);
  await tick();
  await card.updateComplete;
  return card;
}

const buttons = (card: Card) => [...card.shadowRoot!.querySelectorAll<HTMLButtonElement>("button.action")];
const dialog = () => document.body.querySelector("cospend-bill-dialog") as Dialog | null;
const dialogRoot = () => dialog()!.shadowRoot!;

describe("cospend-actions-card", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("affiche trois boutons", async () => {
    const card = await mount(makeHass().hass);
    expect(buttons(card).map((b) => b.className)).toEqual(["action add", "action edit", "action delete"]);
    expect(buttons(card).every((b) => !b.disabled)).toBe(true);
    expect(card.getCardSize()).toBeGreaterThan(0);
  });

  it("masque les boutons désactivés dans la configuration", async () => {
    const card = await mount(makeHass().hass, { show_edit: false, show_delete: false });
    expect(buttons(card)).toHaveLength(1);
  });

  it("désactive les boutons en lecture seule", async () => {
    const card = await mount(makeHass([project({ can_write: false })]).hass);
    expect(buttons(card).every((b) => b.disabled)).toBe(true);
    expect(card.shadowRoot!.textContent).toContain("Lecture seule");
  });

  it("désactive les boutons avec allow_write: false", async () => {
    const card = await mount(makeHass().hass, { allow_write: false });
    expect(buttons(card).every((b) => b.disabled)).toBe(true);
  });

  it("choisit le projet configuré", async () => {
    const { hass } = makeHass([project(), project({ id: "autre", name: "Autre" })]);
    const card = await mount(hass, { project: "autre" });
    expect(card.shadowRoot!.querySelector(".title")!.textContent).toBe("Autre");
  });

  it("ouvre la fenêtre d'ajout avec le formulaire", async () => {
    const card = await mount(makeHass().hass);
    buttons(card)[0].click();
    await tick();
    const d = dialog()!;
    await d.updateComplete;
    expect(d).not.toBeNull();
    expect(dialogRoot().querySelector("cospend-bill-form")).not.toBeNull();
    expect(dialogRoot().querySelector("select[name=bill]")).toBeNull();
  });

  it("modifier : liste déroulante des dépenses, puis formulaire pré-rempli", async () => {
    const { hass, calls } = makeHass();
    const card = await mount(hass);
    buttons(card)[1].click();
    await tick();
    const d = dialog()!;
    await d.updateComplete;
    const select = dialogRoot().querySelector<HTMLSelectElement>("select[name=bill]")!;
    expect(select.options).toHaveLength(3);
    expect(calls.some((c) => c.type === "cospend/bills")).toBe(true);
    expect(dialogRoot().querySelector("cospend-bill-form")).toBeNull();
    select.value = "2";
    select.dispatchEvent(new Event("change"));
    await tick();
    await d.updateComplete;
    const form = dialogRoot().querySelector("cospend-bill-form") as HTMLElement & { bill?: BillItem };
    expect(form.bill?.what).toBe("Essence");
  });

  it("supprimer : confirmation puis appel du service", async () => {
    const { hass, calls } = makeHass();
    const card = await mount(hass);
    buttons(card)[2].click();
    await tick();
    const d = dialog()!;
    await d.updateComplete;
    const select = dialogRoot().querySelector<HTMLSelectElement>("select[name=bill]")!;
    select.value = "1";
    select.dispatchEvent(new Event("change"));
    await tick();
    await d.updateComplete;
    dialogRoot().querySelector<HTMLButtonElement>("button.danger")!.click();
    await d.updateComplete;
    expect(calls.some((c) => c.type === "call_service")).toBe(false);
    dialogRoot().querySelector<HTMLButtonElement>("button.danger.solid")!.click();
    await tick();
    const call = calls.find((c) => c.type === "call_service")!;
    expect(call).toMatchObject({ service: "delete_bill", service_data: { project: "voyage", bill_id: 1 } });
    expect(dialog()).toBeNull();
    await card.updateComplete;
    expect(card.shadowRoot!.querySelector("[role=status]")!.textContent).toContain("supprim");
  });

  it("Échap ferme la fenêtre sans rien envoyer", async () => {
    const { hass, calls } = makeHass();
    const card = await mount(hass);
    buttons(card)[2].click();
    await tick();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await tick();
    expect(dialog()).toBeNull();
    expect(calls.some((c) => c.type === "call_service")).toBe(false);
  });

  it("retire la fenêtre quand la carte quitte la page", async () => {
    const card = await mount(makeHass().hass);
    buttons(card)[0].click();
    await tick();
    expect(dialog()).not.toBeNull();
    card.remove();
    expect(dialog()).toBeNull();
  });
});
