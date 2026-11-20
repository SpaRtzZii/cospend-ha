import { beforeEach, describe, expect, it } from "vitest";

import "../src/manage";
import type { HassLike, Project } from "../src/types";

const project = {
  entry_id: "e1",
  id: "voyage",
  name: "Voyage",
  currency: "EUR",
  access_level: 4,
  members: [
    { id: 1, name: "Alice", activated: true, weight: 1, color: "#336699", balance: 0 },
    { id: 2, name: "Bob", activated: false, weight: 2, color: null, balance: 0 },
  ],
  categories: [{ id: 7, name: "Courses", icon: "🛒", color: "#ffaa00" }],
  payment_modes: [],
  currencies: [{ id: 3, name: "USD", exchange_rate: 0.92 }],
} as unknown as Project;

type Manage = HTMLElement & {
  hass?: HassLike;
  project?: Project;
  updateComplete: Promise<boolean>;
};

async function mount(calls: Array<Record<string, unknown>>, fail = false): Promise<Manage> {
  const element = document.createElement("cospend-manage") as Manage;
  element.hass = {
    language: "fr",
    callWS: async (message: Record<string, unknown>) => {
      if (fail) throw { message: "refusé" };
      calls.push(message);
      return { response: { id: 9 } } as never;
    },
    connection: {} as never,
  } as HassLike;
  element.project = project;
  document.body.append(element);
  await element.updateComplete;
  return element;
}

const root = (element: Manage) => element.shadowRoot!;
const click = async (element: Manage, selector: string, index = 0) => {
  (root(element).querySelectorAll(selector)[index] as HTMLElement).click();
  await element.updateComplete;
};
const setText = async (element: Manage, name: string, value: string) => {
  const input = root(element).querySelector(`input[name="${name}"]`) as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event("input"));
  await element.updateComplete;
};
const submit = async (element: Manage) => {
  root(element).querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await element.updateComplete;
};

describe("cospend-manage", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("liste les membres, avec le poids et l'état", async () => {
    const element = await mount([]);
    const rows = root(element).querySelectorAll("li.row");
    expect(rows).toHaveLength(2);
    expect(rows[1].textContent).toContain("Bob");
    expect(rows[1].textContent).toContain("désactivé");
    expect(rows[1].classList.contains("dim")).toBe(true);
  });

  it("change d'onglet", async () => {
    const element = await mount([]);
    await click(element, ".tab", 1);
    expect(root(element).querySelector("li.row")!.textContent).toContain("Courses");
    await click(element, ".tab", 2);
    expect(root(element).querySelector("li.empty")).not.toBeNull();
    await click(element, ".tab", 3);
    expect(root(element).textContent).toContain("0.92");
  });

  it("ajoute un membre", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(calls);
    let changed = "";
    element.addEventListener("changed", (e) => (changed = (e as CustomEvent).detail.text));
    await click(element, "button.add");
    await setText(element, "name", "Zoé");
    await submit(element);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      type: "call_service",
      domain: "cospend",
      service: "add_member",
      service_data: { project: "voyage", name: "Zoé", weight: 1, active: true },
    });
    expect(changed).toBe("Ajouté");
    expect(root(element).querySelector("form")).toBeNull(); // retour à la liste
  });

  it("refuse un nom vide sans appeler le serveur", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(calls);
    await click(element, "button.add");
    await submit(element);
    expect(calls).toHaveLength(0);
    expect(root(element).querySelector(".error")!.textContent).toContain("nom");
  });

  it("modifie seulement ce qui change et ne rappelle pas le serveur sinon", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(calls);
    await click(element, "button.edit", 0);
    await submit(element); // rien changé
    expect(calls).toHaveLength(0);
    expect(root(element).querySelector("form")).toBeNull();
    await click(element, "button.edit", 0);
    await setText(element, "name", "Alicia");
    await submit(element);
    expect(calls[0]).toMatchObject({
      service: "update_member",
      service_data: { project: "voyage", member: "1", new_name: "Alicia" },
    });
  });

  it("demande confirmation avant de supprimer", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(calls);
    await click(element, "button.remove", 0);
    expect(root(element).querySelector(".confirm")!.textContent).toContain("désactive seulement");
    await click(element, ".confirm .secondary");
    expect(calls).toHaveLength(0);
    await click(element, "button.remove", 0);
    await click(element, ".confirm .yes");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(calls[0]).toMatchObject({
      service: "delete_member",
      service_data: { project: "voyage", member: "1" },
    });
  });

  it("crée une devise avec un taux", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(calls);
    await click(element, ".tab", 3);
    await click(element, "button.add");
    await setText(element, "name", "GBP");
    await setText(element, "rate", "1,17");
    await submit(element);
    expect(calls[0]).toMatchObject({
      service: "add_currency",
      service_data: { project: "voyage", name: "GBP", exchange_rate: "1.17" },
    });
  });

  it("affiche l'erreur du serveur", async () => {
    const element = await mount([], true);
    await click(element, "button.add");
    await setText(element, "name", "Zoé");
    await submit(element);
    expect(root(element).querySelector(".error")!.textContent).toContain("refusé");
    expect(root(element).querySelector("form")).not.toBeNull(); // on garde la saisie
  });

  it("prévient quand on quitte l'écran", async () => {
    const element = await mount([]);
    let closed = false;
    element.addEventListener("close", () => (closed = true));
    await click(element, ".top button");
    expect(closed).toBe(true);
  });
});
