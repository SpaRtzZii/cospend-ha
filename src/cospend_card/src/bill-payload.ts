// État du formulaire de dépense et conversion vers les services ``add_bill`` / ``update_bill``.

import { evaluateAmount } from "./amount";
import type { BillItem, Member, Project } from "./types";

export type SplitKind = "even" | "amounts" | "percent";

export interface FormState {
  what: string;
  amount: string;
  payer: number | null;
  owers: number[];
  date: string;
  category: string;
  mode: string;
  comment: string;
  split: SplitKind;
  shares: Record<number, string>;
  currency: string;
  rate: string;
  repeat: string;
  freq: string;
  until: string;
  allActive: boolean;
}

/** Date du jour au format ``AAAA-MM-JJ`` dans le fuseau du navigateur. */
export function today(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Payeur proposé : le membre qui porte le nom de l'utilisateur connecté, sinon le premier actif. */
export function defaultPayer(members: Member[], userName: string | undefined): number | null {
  const active = members.filter((member) => member.activated);
  const mine = userName
    ? active.find((member) => member.name.trim().toLowerCase() === userName.trim().toLowerCase())
    : undefined;
  return (mine ?? active[0])?.id ?? null;
}

const clean = (value: number): string => String(Math.round(value * 100) / 100);

/** État initial : une dépense vierge, ou les valeurs de ``bill`` pour la modifier. */
export function initialState(
  project: Project,
  bill: BillItem | undefined,
  userName: string | undefined,
): FormState {
  const blank: FormState = {
    what: "",
    amount: "",
    payer: defaultPayer(project.members, userName),
    owers: project.members.filter((member) => member.activated).map((member) => member.id),
    date: today(),
    category: "",
    mode: "",
    comment: "",
    split: "even",
    shares: {},
    currency: "",
    rate: "",
    repeat: "n",
    freq: "1",
    until: "",
    allActive: false,
  };
  if (!bill) return blank;
  return {
    ...blank,
    what: bill.what,
    amount: clean(bill.foreign ? bill.foreign.amount : bill.amount),
    payer: bill.payer_id,
    owers: [...bill.ower_ids],
    date: bill.date || blank.date,
    category: bill.category_id ? String(bill.category_id) : "",
    mode: bill.payment_mode_id > 0 ? String(bill.payment_mode_id) : "",
    comment: bill.comment,
    currency: bill.foreign?.currency ?? "",
    rate: bill.foreign ? String(bill.foreign.rate) : "",
    repeat: bill.repeat || "n",
    freq: String(bill.repeat_freq ?? 1),
    until: bill.repeat_until ?? "",
    allActive: bill.repeat_all_active ?? false,
  };
}

/** Somme des parts saisies (montants ou pourcentages) des participants sélectionnés. */
export function sharesSum(state: FormState): number {
  return state.owers.reduce((sum, id) => sum + (evaluateAmount(state.shares[id] ?? "") ?? 0), 0);
}

/** Message d'erreur de saisie (clé de traduction) ou ``null`` si le formulaire est complet. */
export function validate(state: FormState, locked = false): string | null {
  if (!state.what.trim() || state.payer === null) return "error_required";
  if (!locked && (!state.amount.trim() || state.owers.length === 0)) return "error_required";
  if (!locked) {
    const value = evaluateAmount(state.amount);
    if (value !== null && value <= 0) return "error_amount";
    if (
      state.split !== "even" &&
      state.owers.some((id) => !(state.shares[id] ?? "").trim())
    ) {
      return "error_shares";
    }
  }
  return null;
}

function repeatFields(state: FormState): Record<string, unknown> {
  if (state.repeat === "n") return {};
  return {
    repeat: state.repeat,
    repeat_frequency: Number(state.freq) || 1,
    ...(state.until ? { repeat_until: state.until } : {}),
    ...(state.allActive ? { repeat_all_active: true } : {}),
  };
}

/** Données du service ``cospend.add_bill``. */
export function toCreate(project: Project, state: FormState): Record<string, unknown> {
  const shares =
    state.split === "even"
      ? {}
      : {
          shares: Object.fromEntries(
            state.owers.map((id) => [String(id), (state.shares[id] ?? "").trim()]),
          ),
        };
  return {
    project: project.id,
    title: state.what.trim(),
    amount: state.amount.trim(),
    payer: String(state.payer),
    owers: state.owers.map(String),
    split_mode: state.split,
    ...shares,
    date: state.date || today(),
    comment: state.comment.trim(),
    ...(state.category ? { category: state.category } : {}),
    ...(state.mode ? { payment_mode: state.mode } : {}),
    ...(state.currency
      ? { currency: state.currency, ...(state.rate.trim() ? { exchange_rate: state.rate.trim() } : {}) }
      : {}),
    ...repeatFields(state),
  };
}

const sameSet = (a: number[], b: number[]) =>
  a.length === b.length && a.every((id) => b.includes(id));

/**
 * Champs modifiés par rapport à ``base`` (données du service ``cospend.update_bill``).
 * ``locked`` : répartition personnalisée, dont le montant, les participants et la devise ne
 * peuvent pas changer.
 */
export function toChanges(
  state: FormState,
  base: FormState,
  locked: boolean,
): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  if (state.what.trim() !== base.what) changes.title = state.what.trim();
  if (!locked) {
    const money =
      state.amount.trim() !== base.amount ||
      state.currency !== base.currency ||
      (state.currency !== "" && state.rate.trim() !== base.rate.trim());
    if (money) {
      changes.amount = state.amount.trim();
      if (state.currency) {
        changes.currency = state.currency;
        if (state.rate.trim()) changes.exchange_rate = state.rate.trim();
      }
    }
    if (!sameSet(state.owers, base.owers)) changes.owers = state.owers.map(String);
  }
  if (state.payer !== base.payer && state.payer !== null) changes.payer = String(state.payer);
  if (state.date !== base.date) changes.date = state.date;
  if (state.category !== base.category) changes.category = state.category;
  if (state.mode !== base.mode) changes.payment_mode = state.mode;
  if (state.comment.trim() !== base.comment) changes.comment = state.comment.trim();

  if (state.repeat !== base.repeat) {
    changes.repeat = state.repeat;
  }
  if (state.repeat !== "n") {
    if (state.repeat !== base.repeat || state.freq !== base.freq) {
      changes.repeat_frequency = Number(state.freq) || 1;
    }
    if (state.until !== base.until) changes.repeat_until = state.until; // "" retire la date de fin
    if (state.allActive !== base.allActive) changes.repeat_all_active = state.allActive;
  }
  return changes;
}
