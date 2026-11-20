import { beforeEach, describe, expect, it } from "vitest";

import "../src/bill-form";
import { defaultPayer, today } from "../src/bill-form";
import type { HassLike, Member, Project } from "../src/types";

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
  currencies: [],
} as Project;

type Form = HTMLElement & {
  hass?: HassLike;
  project?: Project;
  updateComplete: Promise<boolean>;
};

async function mount(callWS: HassLike["callWS"], user = "Bob"): Promise<Form> {
  const form = document.createElement("cospend-bill-form") as Form;
  form.hass = { language: "fr", user: { name: user }, callWS, connection: {} as never };
  form.project = project;
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
    expect((root(form).querySelector("select") as HTMLSelectElement).value).toBe("2");
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
    (selects[1] as HTMLSelectElement).value = "7";
    selects[1].dispatchEvent(new Event("change"));
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
    expect(saved).toEqual({ project: "voyage", bill_ids: [41] });
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
