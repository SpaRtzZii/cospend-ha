import { describe, expect, it } from "vitest";

import { emptyState, stateOf, toDelete, toService, validateItem } from "../src/manage-payload";
import type { Category, Currency, Member } from "../src/types";

const member: Member = {
  id: 12,
  name: "Alice",
  activated: true,
  weight: 1,
  color: "#336699",
  balance: 0,
};
const category: Category = { id: 35, name: "Courses", icon: "🛒", color: "#ffaa00" };
const currency: Currency = { id: 5, name: "USD", exchange_rate: 0.923456 };

describe("validateItem", () => {
  it("exige un nom", () => {
    expect(validateItem("categories", { ...emptyState("categories"), name: "  " })).toBe("error_name");
  });
  it("contrôle le poids d'un membre", () => {
    const ok = { ...emptyState("members"), name: "Zoé" };
    expect(validateItem("members", ok)).toBeNull();
    expect(validateItem("members", { ...ok, weight: "abc" })).toBe("error_weight");
    expect(validateItem("members", { ...ok, weight: "-1" })).toBe("error_weight");
    expect(validateItem("members", { ...ok, weight: "0,5" })).toBeNull();
  });
  it("contrôle le taux d'une devise sans l'arrondir", () => {
    const ok = { ...emptyState("currencies"), name: "USD" };
    expect(validateItem("currencies", { ...ok, rate: "0" })).toBe("error_rate");
    expect(validateItem("currencies", { ...ok, rate: "" })).toBe("error_rate");
    expect(validateItem("currencies", { ...ok, rate: "0,923456" })).toBeNull();
  });
});

describe("toService (création)", () => {
  it("crée un membre", () => {
    const state = { ...emptyState("members"), name: " Zoé ", weight: "2", color: "#112233" };
    expect(toService("members", "p", state)).toEqual({
      service: "add_member",
      data: { project: "p", name: "Zoé", weight: 2, active: true, color: "#112233" },
    });
  });
  it("n'envoie pas de couleur non choisie", () => {
    const state = { ...emptyState("members"), name: "Zoé" };
    expect(toService("members", "p", state)!.data).not.toHaveProperty("color");
  });
  it("crée une catégorie ou un mode de paiement", () => {
    const state = { ...emptyState("categories"), name: "Sport", icon: "🎾", color: "#00ff00" };
    expect(toService("categories", "p", state)).toEqual({
      service: "add_category",
      data: { project: "p", name: "Sport", icon: "🎾", color: "#00ff00" },
    });
    expect(toService("payment_modes", "p", { ...state, name: "Cash" })!.service).toBe(
      "add_payment_mode",
    );
  });
  it("crée une devise avec son taux exact", () => {
    const state = { ...emptyState("currencies"), name: "USD", rate: "0,923456" };
    expect(toService("currencies", "p", state)).toEqual({
      service: "add_currency",
      data: { project: "p", name: "USD", exchange_rate: "0.923456" },
    });
  });
});

describe("toService (modification)", () => {
  const base = { id: 12, state: stateOf("members", member) };

  it("ne fait rien sans changement", () => {
    expect(toService("members", "p", { ...base.state }, base)).toBeNull();
  });
  it("n'envoie que les champs modifiés", () => {
    expect(toService("members", "p", { ...base.state, name: "Alicia" }, base)).toEqual({
      service: "update_member",
      data: { project: "p", member: "12", new_name: "Alicia" },
    });
    expect(
      toService("members", "p", { ...base.state, weight: "2", active: false }, base)!.data,
    ).toEqual({ project: "p", member: "12", weight: 2, active: false });
  });
  it("modifie une catégorie", () => {
    const cat = { id: 35, state: stateOf("categories", category) };
    expect(toService("categories", "p", { ...cat.state, icon: "🥖" }, cat)).toEqual({
      service: "update_category",
      data: { project: "p", category: "35", icon: "🥖" },
    });
  });
  it("modifie le taux d'une devise", () => {
    const cur = { id: 5, state: stateOf("currencies", currency) };
    expect(cur.state.rate).toBe("0.923456");
    expect(toService("currencies", "p", { ...cur.state, rate: "0,95" }, cur)!.data).toEqual({
      project: "p",
      currency: "5",
      exchange_rate: "0.95",
    });
  });
});

describe("toDelete", () => {
  it("désigne l'élément par son identifiant", () => {
    expect(toDelete("payment_modes", "p", 17)).toEqual({
      service: "delete_payment_mode",
      data: { project: "p", payment_mode: "17" },
    });
    expect(toDelete("currencies", "p", 5).service).toBe("delete_currency");
  });
});
