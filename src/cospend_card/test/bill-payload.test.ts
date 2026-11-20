import { describe, expect, it } from "vitest";

import { initialState, sharesSum, toChanges, toCreate, validate } from "../src/bill-payload";
import type { BillItem, Project } from "../src/types";

const project = {
  id: "voyage",
  entry_id: "e1",
  members: [
    { id: 1, name: "Alice", activated: true, weight: 1, color: null, balance: 0 },
    { id: 2, name: "Bob", activated: true, weight: 1, color: null, balance: 0 },
  ],
} as unknown as Project;

const bill = (extra: Partial<BillItem> = {}): BillItem => ({
  ids: [5],
  id: 5,
  is_group: false,
  what: "Loyer",
  amount: 900,
  date: "2026-11-01",
  timestamp: 1,
  payer_id: 1,
  ower_ids: [1, 2],
  category_id: 0,
  payment_mode_id: 0,
  comment: "",
  repeat: "m",
  repeat_freq: 1,
  repeat_until: null,
  repeat_all_active: false,
  foreign: null,
  pending: false,
  ...extra,
});

describe("toCreate", () => {
  it("n'envoie que les champs renseignés", () => {
    const state = { ...initialState(project, undefined, "Bob"), what: " Pain ", amount: "2,5" };
    expect(toCreate(project, state)).toMatchObject({
      project: "voyage",
      title: "Pain",
      amount: "2,5",
      payer: "2",
      owers: ["1", "2"],
      split_mode: "even",
      comment: "",
    });
    const data = toCreate(project, state);
    for (const key of ["category", "payment_mode", "currency", "repeat", "shares"]) {
      expect(data).not.toHaveProperty(key);
    }
  });
});

describe("toChanges", () => {
  const base = initialState(project, bill(), undefined);

  it("est vide sans modification", () => {
    expect(toChanges({ ...base }, base, false)).toEqual({});
  });
  it("ne renvoie pas la date inchangée (l'heure serait perdue)", () => {
    expect(toChanges({ ...base, what: "Autre" }, base, false)).toEqual({ title: "Autre" });
    expect(toChanges({ ...base, date: "2026-11-02" }, base, false)).toEqual({ date: "2026-11-02" });
  });
  it("renvoie catégorie et mode vides pour les retirer", () => {
    const withCategory = initialState(project, bill({ category_id: 4, payment_mode_id: 3 }), undefined);
    expect(toChanges({ ...withCategory, category: "", mode: "" }, withCategory, false)).toEqual({
      category: "",
      payment_mode: "",
    });
  });
  it("garde la catégorie interne des remboursements si on n'y touche pas", () => {
    const refund = initialState(project, bill({ category_id: -11 }), undefined);
    expect(toChanges({ ...refund }, refund, false)).toEqual({});
  });
  it("envoie montant, devise et taux ensemble", () => {
    expect(
      toChanges({ ...base, currency: "USD", rate: "0.9" }, base, false),
    ).toEqual({ amount: "900", currency: "USD", exchange_rate: "0.9" });
  });
  it("ignore montant, participants et devise d'un groupe", () => {
    expect(
      toChanges({ ...base, amount: "1", owers: [1], currency: "USD", what: "G" }, base, true),
    ).toEqual({ title: "G" });
  });
  it("gère la répétition", () => {
    expect(toChanges({ ...base, repeat: "w" }, base, false)).toEqual({
      repeat: "w",
      repeat_frequency: 1,
    });
    expect(toChanges({ ...base, until: "2027-01-01", allActive: true }, base, false)).toEqual({
      repeat_until: "2027-01-01",
      repeat_all_active: true,
    });
    expect(toChanges({ ...base, repeat: "n" }, base, false)).toEqual({ repeat: "n" });
    const ending = initialState(project, bill({ repeat_until: "2027-01-01" }), undefined);
    expect(toChanges({ ...ending, until: "" }, ending, false)).toEqual({ repeat_until: "" });
  });
});

describe("validate", () => {
  const ok = { ...initialState(project, undefined, "Bob"), what: "A", amount: "5" };
  it("accepte un formulaire complet", () => {
    expect(validate(ok)).toBeNull();
  });
  it("refuse titre, montant ou participants manquants", () => {
    expect(validate({ ...ok, what: " " })).toBe("error_required");
    expect(validate({ ...ok, amount: "" })).toBe("error_required");
    expect(validate({ ...ok, owers: [] })).toBe("error_required");
    expect(validate({ ...ok, amount: "0" })).toBe("error_amount");
  });
  it("exige les parts d'une répartition personnalisée", () => {
    expect(validate({ ...ok, split: "percent", shares: { 1: "50" } })).toBe("error_shares");
    expect(validate({ ...ok, split: "percent", shares: { 1: "50", 2: "50" } })).toBeNull();
  });
  it("ne contrôle ni montant ni participants d'un groupe verrouillé", () => {
    expect(validate({ ...ok, amount: "", owers: [] }, true)).toBeNull();
  });
});

describe("sharesSum", () => {
  it("additionne les parts des participants sélectionnés", () => {
    const state = {
      ...initialState(project, undefined, undefined),
      shares: { 1: "12,5", 2: "7.5", 3: "100" },
    };
    expect(sharesSum(state)).toBe(20);
  });
});
