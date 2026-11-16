import { describe, expect, it } from "vitest";

import "../src/cospend-card";

describe("cospend-card", () => {
  it("est enregistrée comme élément personnalisé", () => {
    expect(customElements.get("cospend-card")).toBeDefined();
  });

  it("est déclarée dans la liste des cartes personnalisées", () => {
    expect(window.customCards?.some((card) => card.type === "cospend-card")).toBe(true);
  });

  it("accepte une configuration", () => {
    const card = document.createElement("cospend-card") as HTMLElement & {
      setConfig(config: { type: string; title?: string }): void;
      getCardSize(): number;
    };
    card.setConfig({ type: "custom:cospend-card", title: "Test" });
    expect(card.getCardSize()).toBe(2);
  });
});
