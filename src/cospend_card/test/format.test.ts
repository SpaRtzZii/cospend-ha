import { describe, expect, it } from "vitest";

import {
  balanceWidth,
  formatAmount,
  formatDate,
  initials,
  memberColor,
  readableOn,
} from "../src/format";
import { dictionaries, pickLanguage, translate } from "../src/i18n";
import type { Member } from "../src/types";

const member = (balance: number): Member => ({
  id: 1,
  name: "A",
  activated: true,
  weight: 1,
  color: null,
  balance,
});

describe("formatAmount", () => {
  it("utilise Intl pour un code ISO", () => {
    expect(formatAmount(12.5, "EUR", "fr")).toMatch(/12,50\s*€/);
    expect(formatAmount(12.5, "USD", "en")).toBe("$12.50");
  });

  it("accepte un nom ou un symbole libre", () => {
    expect(formatAmount(12.5, "pts", "en")).toBe("12.50 pts");
    expect(formatAmount(12.5, "€", "en")).toBe("12.50 €");
    expect(formatAmount(12.5, null, "en")).toBe("12.50");
  });

  it("affiche le signe des soldes à la demande", () => {
    expect(formatAmount(5, null, "en", { sign: true })).toBe("+5.00");
    expect(formatAmount(-5, null, "en", { sign: true })).toBe("-5.00");
    expect(formatAmount(-5, null, "en")).toBe("-5.00");
  });

  it("ne plante pas sur un code ISO inconnu", () => {
    expect(formatAmount(1, "ZZZ", "en")).toContain("1.00");
  });
});

describe("formatDate", () => {
  it("n'est pas décalée par le fuseau horaire", () => {
    expect(formatDate("2026-11-15", "en")).toContain("15");
    expect(formatDate("2026-11-15", "en")).toContain("2026");
  });
  it("laisse passer une valeur illisible", () => {
    expect(formatDate("bientôt", "en")).toBe("bientôt");
  });
});

describe("pastilles", () => {
  it("calcule les initiales", () => {
    expect(initials("util1")).toBe("U1");
    expect(initials("util2")).toBe("U2");
    expect(initials("Alice")).toBe("AL");
    expect(initials("Marie Curie")).toBe("MC");
    expect(initials("  ")).toBe("?");
  });
  it("garde la couleur du serveur, sinon une teinte stable", () => {
    expect(memberColor({ name: "A", color: "#112233" })).toBe("#112233");
    const first = memberColor({ name: "Alice", color: null });
    expect(first).toBe(memberColor({ name: "Alice", color: null }));
    expect(first).toMatch(/^hsl\(/);
  });
  it("choisit un texte lisible", () => {
    expect(readableOn("#ffffff")).toBe("#1c1c1c");
    expect(readableOn("#000000")).toBe("#fff");
  });
});

describe("balanceWidth", () => {
  it("est relative au plus grand solde absolu", () => {
    const members = [member(100), member(-50), member(0)];
    expect(balanceWidth(100, members)).toBe(100);
    expect(balanceWidth(-50, members)).toBe(50);
    expect(balanceWidth(0, members)).toBe(0);
    expect(balanceWidth(0, [member(0)])).toBe(0);
  });
});

describe("traductions", () => {
  it("fournissent les mêmes clés en français et en anglais", () => {
    expect(Object.keys(dictionaries.fr).sort()).toEqual(Object.keys(dictionaries.en).sort());
  });
  it("gardent les mêmes variables dans les deux langues", () => {
    const variables = (text: string) => (text.match(/\{\w+\}/g) ?? []).sort();
    for (const key of Object.keys(dictionaries.en)) {
      expect(variables(dictionaries.fr[key]), key).toEqual(variables(dictionaries.en[key]));
    }
  });
  it("remplacent les variables et retombent sur l'anglais", () => {
    expect(translate("fr", "paid_by", { name: "Léa" })).toBe("Payé par Léa");
    expect(translate("de", "paid_by", { name: "Léa" })).toBe("Paid by Léa");
    expect(pickLanguage("fr-CA")).toBe("fr");
    expect(translate("en", "clé-inconnue")).toBe("clé-inconnue");
  });
});
