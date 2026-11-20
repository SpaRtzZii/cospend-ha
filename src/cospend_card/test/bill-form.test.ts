import { beforeEach, describe, expect, it } from "vitest";

import "../src/bill-form";
import { defaultPayer, today } from "../src/bill-form";
import type { BillItem, HassLike, Member, Project } from "../src/types";

const members: Member[] = [
  { id: 1, name: "Alice", activated: true, weight: 1, color: "#336699", balance: 0 },
  { id: 2, name: "Bob", activated: true, weight: 1, color: null, balance: 0 },
  { id: 3, name: "Zoé", activated: false, weight: 1, color: null, balance: 0 },
];

const project = {
  entry_id: "e1",
  id: "voyage",
  name: "Voyage",
  currency: "EUR",
  archived: false,
  can_write: true,
  access_level: 4,
  total_spent: 0,
  nb_bills: 0,
  pending: 0,
  available: true,
  members,
  categories: [{ id: 7, name: "Courses", icon: "🛒", color: "#fa0" }],
  payment_modes: [{ id: 3, name: "Carte", icon: "💳", color: "" }],
  currencies: [{ id: 1, name: "USD", exchange_rate: 0.92 }],
} as Project;

type Form = HTMLElement & {
  hass?: HassLike;
  project?: Project;
  updateComplete: Promise<boolean>;
};

async function mount(
  callWS: HassLike["callWS"],
  user = "Bob",
  bill?: BillItem,
): Promise<Form> {
  const form = document.createElement("cospend-bill-form") as Form & { bill?: BillItem };
  form.hass = { language: "fr", user: { name: user }, callWS, connection: {} as never };
  form.project = project;
  form.bill = bill;
  document.body.append(form);
  await form.updateComplete;
  return form;
}

const root = (form: Form) => form.shadowRoot!;
const input = (form: Form, selector: string) =>
  root(form).querySelector(selector) as HTMLInputElement;

function type(element: HTMLInputElement, value: string): void {
  element.value = value;
  element.dispatchEvent(new Event("input"));
}

const submit = async (form: Form) => {
  root(form).querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
  for (let i = 0; i < 5; i++) {
    await Promise.resolve();
    await form.updateComplete;
  }
};

describe("assistants du formulaire", () => {
  it("propose le membre qui porte le nom de l'utilisateur, sinon le premier actif", () => {
    expect(defaultPayer(members, "bob")).toBe(2);
    expect(defaultPayer(members, "Inconnu")).toBe(1);
    expect(defaultPayer(members, undefined)).toBe(1);
    expect(defaultPayer(members.filter((m) => !m.activated), "Zoé")).toBeNull();
  });
  it("formate la date du jour", () => {
    expect(today(new Date(2026, 10, 5))).toBe("2026-11-05");
  });
});

describe("cospend-bill-form", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("préremplit le payeur et les participants actifs", async () => {
    const form = await mount(async () => ({}) as never);
    expect((root(form).querySelectorAll("select")[1] as HTMLSelectElement).value).toBe("2");
    const pressed = Array.from(root(form).querySelectorAll(".chip")).map((chip) =>
      chip.getAttribute("aria-pressed"),
    );
    expect(pressed).toEqual(["true", "true"]); // Zoé (inactive) n'est pas proposée
  });

  it("envoie la dépense au service add_bill avec des identifiants", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const form = await mount(async (message) => {
      calls.push(message);
      return { response: { project: "voyage", bill_ids: [41] } } as never;
    });
    let saved: unknown;
    form.addEventListener("saved", (event) => (saved = (event as CustomEvent).detail));
    type(input(form, 'input[type="text"]'), "  Essence ");
    type(root(form).querySelectorAll('input[type="text"]')[1] as HTMLInputElement, "12,5 + 7");
    (root(form).querySelector(".chip") as HTMLButtonElement).click(); // décoche Alice
    await form.updateComplete;
    const selects = root(form).querySelectorAll("select");
    (selects[2] as HTMLSelectElement).value = "7";
    selects[2].dispatchEvent(new Event("change"));
    await submit(form);

    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      type: "call_service",
      domain: "cospend",
      service: "add_bill",
      return_response: true,
      service_data: {
        project: "voyage",
        title: "Essence",
        amount: "12,5 + 7",
        payer: "2",
        owers: ["2"],
        split_mode: "even",
        category: "7",
      },
    });
    expect((calls[0].service_data as Record<string, unknown>).payment_mode).toBeUndefined();
    expect(saved).toMatchObject({ project: "voyage", bill_ids: [41], edited: false });
  });

  it("refuse un formulaire incomplet sans appeler le serveur", async () => {
    let called = false;
    const form = await mount(async () => {
      called = true;
      return {} as never;
    });
    await submit(form);
    expect(called).toBe(false);
    expect(root(form).textContent).toContain("Renseignez le titre");
  });

  it("affiche l'erreur du serveur et reste sur le formulaire", async () => {
    const form = await mount(async () => {
      throw { code: "home_assistant_error", message: "Montant invalide" };
    });
    type(input(form, 'input[type="text"]'), "Essence");
    type(root(form).querySelectorAll('input[type="text"]')[1] as HTMLInputElement, "abc");
    await submit(form);
    expect(root(form).querySelector(".error")!.textContent).toContain("Montant invalide");
  });

  it("montre le résultat d'un calcul", async () => {
    const form = await mount(async () => ({}) as never);
    type(root(form).querySelectorAll('input[type="text"]')[1] as HTMLInputElement, "12,5 + 7");
    await form.updateComplete;
    expect(root(form).querySelector(".preview")!.textContent).toMatch(/19,50\s*€/);
  });
});


const existing = (extra: Partial<BillItem> = {}): BillItem => ({
  ids: [30],
  id: 30,
  is_group: false,
  what: "Pizza",
  amount: 20,
  date: "2026-11-15",
  timestamp: 1000,
  payer_id: 1,
  ower_ids: [1, 2],
  category_id: 7,
  payment_mode_id: 0,
  comment: "midi",
  repeat: "n",
  foreign: null,
  pending: false,
  ...extra,
});

const texts = (form: Form) =>
  Array.from(root(form).querySelectorAll('input[type="text"]')) as HTMLInputElement[];

describe("modification", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("préremplit la dépense et n'envoie que ce qui change", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const form = await mount(
      async (message) => {
        calls.push(message);
        return { response: { bill_ids: [30] } } as never;
      },
      "Bob",
      existing(),
    );
    expect(texts(form)[0].value).toBe("Pizza");
    expect(texts(form)[1].value).toBe("20");
    expect(root(form).querySelector("h2")!.textContent).toContain("Modifier");
    type(texts(form)[0], "Pizza royale");
    await submit(form);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      service: "update_bill",
      service_data: { project: "voyage", bill_id: 30, title: "Pizza royale" },
    });
    expect(Object.keys(calls[0].service_data as object).sort()).toEqual(
      ["bill_id", "project", "title"],
    );
  });

  it("n'appelle pas le serveur quand rien n'a changé", async () => {
    let called = false;
    const form = await mount(
      async () => {
        called = true;
        return {} as never;
      },
      "Bob",
      existing(),
    );
    let cancelled = false;
    form.addEventListener("cancel", () => (cancelled = true));
    await submit(form);
    expect(called).toBe(false);
    expect(cancelled).toBe(true);
  });

  it("verrouille montant, participants et devise d'une répartition personnalisée", async () => {
    const form = await mount(
      async () => ({}) as never,
      "Bob",
      existing({ is_group: true, ids: [30, 31, 32] }),
    );
    expect(texts(form)[1].disabled).toBe(true);
    expect(root(form).querySelector("fieldset")!.disabled).toBe(true);
    expect(root(form).querySelector(".info")!.textContent).toContain("recréez");
  });

  it("reprend la devise étrangère d'origine", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const form = await mount(
      async (message) => {
        calls.push(message);
        return {} as never;
      },
      "Bob",
      existing({ amount: 92, foreign: { currency: "USD", amount: 100, rate: 0.92 } }),
    );
    expect(texts(form)[1].value).toBe("100");
    type(texts(form)[1], "120");
    await submit(form);
    expect(calls[0].service_data).toMatchObject({
      amount: "120",
      currency: "USD",
      exchange_rate: "0.92",
    });
  });

  it("prévient quand les poids des participants étaient inégaux", async () => {
    const form = await mount(
      async () => ({}) as never,
      "Bob",
      existing({ uneven_weights: true }),
    );
    expect(root(form).querySelector(".warn")!.textContent).toContain("poids inégaux");
  });
});

describe("création avancée", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("répartit en montants avec la somme des parts", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const form = await mount(async (message) => {
      calls.push(message);
      return { response: {} } as never;
    });
    type(texts(form)[0], "Resto");
    type(texts(form)[1], "100");
    (root(form).querySelectorAll(".segment")[1] as HTMLButtonElement).click();
    await form.updateComplete;
    const shares = root(form).querySelectorAll(".shares input");
    expect(shares).toHaveLength(2);
    type(shares[0] as HTMLInputElement, "60");
    type(shares[1] as HTMLInputElement, "30");
    await form.updateComplete;
    expect(root(form).textContent!.replace(/\s+/g, " ")).toContain("Total des parts : 90 / 100");
    type(shares[1] as HTMLInputElement, "40");
    await submit(form);
    expect(calls[0].service_data).toMatchObject({
      split_mode: "amounts",
      shares: { "1": "60", "2": "40" },
    });
  });

  it("répartit en pourcentages et exige toutes les parts", async () => {
    let called = false;
    const form = await mount(async () => {
      called = true;
      return {} as never;
    });
    type(texts(form)[0], "Loyer");
    type(texts(form)[1], "900");
    (root(form).querySelectorAll(".segment")[2] as HTMLButtonElement).click();
    await form.updateComplete;
    await submit(form);
    expect(called).toBe(false);
    expect(root(form).textContent).toContain("part de chacun");
    expect(root(form).textContent).toContain("doit faire 100");
  });

  it("convertit avec la devise du projet et envoie le taux", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const form = await mount(async (message) => {
      calls.push(message);
      return { response: {} } as never;
    });
    type(texts(form)[0], "Hôtel");
    type(texts(form)[1], "100");
    const select = root(form).querySelector(".grid select") as HTMLSelectElement;
    select.value = "USD";
    select.dispatchEvent(new Event("change"));
    await form.updateComplete;
    expect(texts(form)[2].value).toBe("0.92"); // taux repris du projet
    expect(root(form).textContent).toMatch(/= 92,00\s*€ dans la devise du projet/);
    await submit(form);
    expect(calls[0].service_data).toMatchObject({ currency: "USD", exchange_rate: "0.92" });
  });

  it("envoie la répétition", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const form = await mount(async (message) => {
      calls.push(message);
      return { response: {} } as never;
    });
    type(texts(form)[0], "Loyer");
    type(texts(form)[1], "900");
    const repeat = root(form).querySelector("details select") as HTMLSelectElement;
    repeat.value = "m";
    repeat.dispatchEvent(new Event("change"));
    await form.updateComplete;
    type(root(form).querySelector('details input[type="number"]') as HTMLInputElement, "2");
    type(root(form).querySelectorAll('details input[type="date"]')[0] as HTMLInputElement, "2027-06-30");
    await submit(form);
    expect(calls[0].service_data).toMatchObject({
      repeat: "m",
      repeat_frequency: 2,
      repeat_until: "2027-06-30",
    });
  });
});
