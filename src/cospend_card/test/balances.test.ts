import { beforeEach, describe, expect, it } from "vitest";

import "../src/balances";
import type { HassLike, Project } from "../src/types";

const project = {
  entry_id: "e1",
  id: "voyage",
  name: "Voyage",
  currency: "EUR",
  total_spent: 120,
  members: [
    { id: 1, name: "Alice", activated: true, weight: 1, color: "#336699", balance: 40 },
    { id: 2, name: "Bob", activated: true, weight: 1, color: null, balance: -30 },
    { id: 3, name: "Chloé", activated: false, weight: 1, color: null, balance: -10 },
    { id: 4, name: "Dan", activated: true, weight: 1, color: null, balance: 0 },
  ],
} as unknown as Project;

type Balances = HTMLElement & {
  hass?: HassLike;
  project?: Project;
  inline: boolean;
  updateComplete: Promise<boolean>;
};

async function mount(inline = false): Promise<Balances> {
  const element = document.createElement("cospend-balances") as Balances;
  element.hass = { language: "fr", callWS: async () => ({}) as never } as unknown as HassLike;
  element.project = project;
  element.inline = inline;
  document.body.append(element);
  await element.updateComplete;
  return element;
}

const text = (element: Balances) => element.shadowRoot!.textContent!.replace(/\s+/g, " ");

describe("cospend-balances", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("liste chaque membre avec son solde signé", async () => {
    const element = await mount();
    const t = text(element);
    expect(t).toMatch(/Alice.*\+40,00\s*€/);
    expect(t).toMatch(/Bob.*-30,00\s*€/);
    expect(t).toMatch(/Dan.*\+0,00\s*€/);
    expect(element.shadowRoot!.querySelectorAll("li")).toHaveLength(4);
  });

  it("colore les soldes et dessine les barres du bon côté", async () => {
    const element = await mount();
    const root = element.shadowRoot!;
    expect(root.querySelectorAll(".amount.positive")).toHaveLength(1);
    expect(root.querySelectorAll(".amount.negative")).toHaveLength(2);
    expect(root.querySelectorAll(".half.right .fill.positive")).toHaveLength(1);
    expect(root.querySelectorAll(".half.left .fill.negative")).toHaveLength(2);
    // Le plus gros solde absolu occupe toute la demi-barre.
    expect((root.querySelector(".fill.positive") as HTMLElement).style.width).toBe("100%");
  });

  it("signale les membres inactifs", async () => {
    const element = await mount();
    expect(element.shadowRoot!.querySelector("li.inactive")!.textContent).toContain("inactif");
  });

  it("affiche le total dépensé et le bouton retour dans l'écran à part", async () => {
    const element = await mount();
    expect(text(element)).toMatch(/Total dépensé\s*120,00\s*€/);
    let closed = false;
    element.addEventListener("close", () => (closed = true));
    (element.shadowRoot!.querySelector("button.back") as HTMLElement).click();
    expect(closed).toBe(true);
  });

  it("en mode intégré, n'affiche ni retour ni total", async () => {
    const element = await mount(true);
    expect(element.shadowRoot!.querySelector("button.back")).toBeNull();
    expect(text(element)).not.toContain("Total dépensé");
    expect(text(element)).toContain("Soldes");
    expect(element.shadowRoot!.querySelectorAll("li")).toHaveLength(4);
  });
});
