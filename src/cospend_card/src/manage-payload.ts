// Gestion du projet : formulaire → appel de service (fonctions pures, testées à part).

import type { Category, Currency, Member, PaymentMode } from "./types";

export type Kind = "members" | "categories" | "payment_modes" | "currencies";
export type Item = Member | Category | PaymentMode | Currency;

export const KINDS: Kind[] = ["members", "categories", "payment_modes", "currencies"];

export interface ItemState {
  name: string;
  weight: string;
  color: string;
  active: boolean;
  icon: string;
  rate: string;
}

export interface ServiceCallSpec {
  service: string;
  data: Record<string, unknown>;
}

const SERVICE_NAME: Record<Kind, string> = {
  members: "member",
  categories: "category",
  payment_modes: "payment_mode",
  currencies: "currency",
};

/** Nom du champ qui désigne l'élément à modifier ou à supprimer. */
const REF_FIELD: Record<Kind, string> = SERVICE_NAME;

export function emptyState(kind: Kind): ItemState {
  return { name: "", weight: "1", color: "", active: true, icon: "", rate: kind === "currencies" ? "1" : "" };
}

export function stateOf(kind: Kind, item: Item): ItemState {
  const base = emptyState(kind);
  base.name = item.name;
  if (kind === "members") {
    const member = item as Member;
    base.weight = String(member.weight);
    base.color = member.color ?? "";
    base.active = member.activated;
  } else if (kind === "currencies") {
    base.rate = String((item as Currency).exchange_rate);
  } else {
    const labelled = item as Category | PaymentMode;
    base.icon = labelled.icon ?? "";
    base.color = labelled.color ?? "";
  }
  return base;
}

/** Nombre décimal (virgule ou point), sans arrondi : les taux ont plus de 2 décimales. */
function number(text: string): number | null {
  const clean = text.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(clean)) return null;
  return Number(clean);
}

/** Clé de traduction de l'erreur de saisie, ou ``null`` si le formulaire est valide. */
export function validateItem(kind: Kind, state: ItemState): string | null {
  if (!state.name.trim()) return "error_name";
  if (kind === "members") {
    const weight = number(state.weight);
    if (weight === null || weight < 0) return "error_weight";
  }
  if (kind === "currencies") {
    const rate = number(state.rate);
    if (rate === null || rate <= 0) return "error_rate";
  }
  return null;
}

/** Service à appeler pour créer (``base`` absent) ou modifier (seuls les champs changés). */
export function toService(
  kind: Kind,
  project: string,
  state: ItemState,
  base?: { id: number; state: ItemState },
): ServiceCallSpec | null {
  const noun = SERVICE_NAME[kind];
  const name = state.name.trim();
  if (!base) {
    const data: Record<string, unknown> = { project, name };
    if (kind === "members") {
      data.weight = number(state.weight);
      data.active = state.active;
      if (state.color) data.color = state.color;
    } else if (kind === "currencies") {
      data.exchange_rate = String(number(state.rate));
    } else {
      if (state.icon) data.icon = state.icon;
      if (state.color) data.color = state.color;
    }
    return { service: `add_${noun}`, data };
  }

  const data: Record<string, unknown> = { project, [REF_FIELD[kind]]: String(base.id) };
  const before = base.state;
  if (name !== before.name) data.new_name = name;
  if (kind === "members") {
    if (number(state.weight) !== number(before.weight)) data.weight = number(state.weight);
    if (state.color && state.color !== before.color) data.color = state.color;
    if (state.active !== before.active) data.active = state.active;
  } else if (kind === "currencies") {
    if (number(state.rate) !== number(before.rate)) data.exchange_rate = String(number(state.rate));
  } else {
    if (state.icon !== before.icon) data.icon = state.icon;
    if (state.color && state.color !== before.color) data.color = state.color;
  }
  return Object.keys(data).length > 2 ? { service: `update_${noun}`, data } : null;
}

export function toDelete(kind: Kind, project: string, id: number): ServiceCallSpec {
  return {
    service: `delete_${SERVICE_NAME[kind]}`,
    data: { project, [REF_FIELD[kind]]: String(id) },
  };
}
