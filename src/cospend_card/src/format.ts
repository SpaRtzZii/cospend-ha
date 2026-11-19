// Mise en forme : montants, dates, pastilles de membres.

import type { Member, Project } from "./types";

const ISO_CURRENCY = /^[A-Z]{3}$/;

/** Montant avec la devise du projet : code ISO (EUR) géré par Intl, sinon symbole ou nom libre. */
export function formatAmount(
  value: number,
  currency: string | null | undefined,
  language = "en",
  options: { sign?: boolean } = {},
): string {
  const lang = language || "en";
  const sign: "always" | "auto" = options.sign ? "always" : "auto";
  const name = currency?.trim();
  if (name && ISO_CURRENCY.test(name)) {
    try {
      return new Intl.NumberFormat(lang, {
        style: "currency",
        currency: name,
        signDisplay: sign,
      }).format(value);
    } catch {
      // Code inconnu : repli sur le nom libre ci-dessous.
    }
  }
  const number = new Intl.NumberFormat(lang, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: sign,
  }).format(value);
  return name ? `${number} ${name}` : number;
}

/** « 2026-11-15 » devient une date locale (sans décalage de fuseau). */
export function formatDate(date: string, language = "en"): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date);
  if (!match) return date;
  const parsed = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return new Intl.DateTimeFormat(language || "en", { dateStyle: "medium" }).format(parsed);
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) {
    const letters = Array.from(words[0]);
    // « util1 », « util2 » : la première lettre et le chiffre final distinguent les membres.
    const last = letters[letters.length - 1];
    return (/\d/.test(last) && letters.length > 1 ? letters[0] + last : letters.slice(0, 2).join("")).toUpperCase();
  }
  return (Array.from(words[0])[0] + Array.from(words[1])[0]).toUpperCase();
}

/** Couleur du membre, sinon une teinte stable déduite du nom. */
export function memberColor(member: Pick<Member, "name" | "color">): string {
  if (member.color) return member.color;
  let hash = 0;
  for (const char of member.name) hash = (hash * 31 + char.codePointAt(0)!) % 360;
  return `hsl(${hash} 55% 45%)`;
}

/** Texte lisible (noir ou blanc) sur une pastille de couleur ``#rrggbb``. */
export function readableOn(color: string): string {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
  if (!match) return "#fff";
  const [r, g, b] = [match[1], match[2], match[3]].map((part) => parseInt(part, 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#1c1c1c" : "#fff";
}

export function memberName(project: Project, id: number): string {
  return project.members.find((member) => member.id === id)?.name ?? String(id);
}

/** Largeur (0 à 100) de la barre d'un solde, relative au plus grand solde absolu. */
export function balanceWidth(balance: number, members: Member[]): number {
  const max = Math.max(0, ...members.map((member) => Math.abs(member.balance)));
  return max === 0 ? 0 : Math.round((Math.abs(balance) / max) * 100);
}

export function projectKey(project: Pick<Project, "entry_id" | "id">): string {
  return `${project.entry_id}:${project.id}`;
}
