import { beforeEach, describe, expect, it } from "vitest";

import "../src/settlement";
import type { HassLike, Project, SettlementPlan } from "../src/types";

const project = {
  entry_id: "e1",
  id: "voyage",
  name: "Voyage",
  currency: "EUR",
  members: [
    { id: 1, name: "Alice", activated: true, weight: 1, color: "#336699", balance: 40 },
    { id: 2, name: "Bob", activated: true, weight: 1, color: null, balance: -30 },
    { id: 3, name: "Chloé", activated: true, weight: 1, color: null, balance: -10 },
  ],
} as unknown as Project;

type Settlement = HTMLElement & {
  hass?: HassLike;
  project?: Project;
  canWrite: boolean;
  updateComplete: Promise<boolean>;
};

const plan = (extra: Partial<SettlementPlan> = {}): SettlementPlan => ({
  source: "server",
  transactions: [
    { from_id: 2, to_id: 1, amount: 30 },
    { from_id: 3, to_id: 1, amount: 10 },
  ],
  pending: 0,
  ...extra,
});

async function mount(
  answer: SettlementPlan | Error,
  calls: Array<Record<string, unknown>> = [],
  options: { canWrite?: boolean; user?: string } = {},
): Promise<Settlement> {
  const element = document.createElement("cospend-settlement") as Settlement;
  element.hass = {
    language: "fr",
    user: { name: options.user ?? "Quentin" },
    callWS: async (message: Record<string, unknown>) => {
      calls.push(message);
      if (message.type === "cospend/settlement") {
        if (answer instanceof Error) throw answer;
        return answer as never;
      }
      return { response: { bill_ids: [9], queued: false } } as never;
    },
    connection: {} as never,
  } as HassLike;
  element.canWrite = options.canWrite ?? true;
  element.project = project;
  document.body.append(element);
  await element.updateComplete;
  await new Promise((resolve) => setTimeout(resolve, 0));
  await element.updateComplete;
  return element;
}

const root = (element: Settlement) => element.shadowRoot!;
const text = (element: Settlement) => root(element).textContent!.replace(/\s+/g, " ");
const click = async (element: Settlement, selector: string, index = 0) => {
  (root(element).querySelectorAll(selector)[index] as HTMLElement).click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  await element.updateComplete;
};

describe("cospend-settlement", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("liste qui doit combien à qui, le plus gros montant d'abord", async () => {
    const element = await mount(plan());
    const rows = root(element).querySelectorAll("li.row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toMatch(/Bob doit 30,00\s*€ à Alice/);
    expect(rows[1].textContent).toMatch(/Chloé doit 10,00\s*€ à Alice/);
  });

  it("met en tête les remboursements de l'utilisateur connecté", async () => {
    const element = await mount(plan(), [], { user: "chloé" });
    const rows = root(element).querySelectorAll("li.row");
    expect(rows[0].textContent).toContain("Chloé doit");
    expect(rows[0].classList.contains("mine")).toBe(true);
  });

  it("annonce que tout est équilibré", async () => {
    const element = await mount(plan({ transactions: [] }));
    expect(text(element)).toContain("équilibre");
    expect(root(element).querySelector("li")).toBeNull();
  });

  it("signale un plan local et les opérations en attente", async () => {
    const element = await mount(plan({ source: "local", pending: 2 }));
    expect(text(element)).toContain("Nextcloud n'a pas répondu");
    expect(text(element)).toContain("2 opération(s) en attente");
  });

  it("affiche l'erreur de calcul", async () => {
    const element = await mount(new Error("oups"));
    expect(root(element).querySelector(".error")!.textContent).toContain("oups");
  });

  it("enregistre le remboursement après confirmation", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(plan(), calls);
    let changed = "";
    element.addEventListener("changed", (e) => (changed = (e as CustomEvent).detail.text));
    await click(element, "button.reimburse", 0);
    expect(text(element)).toContain("Enregistrer le remboursement de 30,00");
    await click(element, "button.yes");
    const write = calls.find((c) => c.type === "call_service")!;
    expect(write).toMatchObject({
      domain: "cospend",
      service: "add_bill",
      service_data: {
        project: "voyage",
        title: "Bob → Alice",
        amount: "30",
        payer: "2",
        owers: ["1"],
        split_mode: "even",
        category: "-11",
      },
    });
    expect(changed).toBe("Remboursement enregistré");
  });

  it("n'enregistre rien si on annule", async () => {
    const calls: Array<Record<string, unknown>> = [];
    const element = await mount(plan(), calls);
    await click(element, "button.reimburse", 0);
    await click(element, "button.no");
    expect(calls.some((c) => c.type === "call_service")).toBe(false);
    expect(root(element).querySelector(".confirm")).toBeNull();
  });

  it("n'offre pas d'enregistrement en lecture seule", async () => {
    const element = await mount(plan(), [], { canWrite: false });
    expect(root(element).querySelector("button.reimburse")).toBeNull();
    expect(root(element).querySelectorAll("li.row")).toHaveLength(2);
  });

  it("annonce un remboursement mis en attente", async () => {
    const element = document.createElement("cospend-settlement") as Settlement;
    element.hass = {
      language: "fr",
      callWS: async (m: Record<string, unknown>) =>
        (m.type === "cospend/settlement" ? plan() : { response: { queued: true } }) as never,
      connection: {} as never,
    } as HassLike;
    element.canWrite = true;
    element.project = project;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));
    await element.updateComplete;
    let changed = "";
    element.addEventListener("changed", (e) => (changed = (e as CustomEvent).detail.text));
    await click(element, "button.reimburse", 0);
    await click(element, "button.yes");
    expect(changed).toContain("mis en attente");
  });
});
