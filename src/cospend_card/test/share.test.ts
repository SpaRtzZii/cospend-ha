import { beforeEach, describe, expect, it } from "vitest";

import "../src/share-dialog";
import { cospendAppLink, qrMatrix, safeShareUrl } from "../src/qr";
import type { HassLike } from "../src/types";

const URL = "https://cloud.example.org/apps/cospend/s/AbCdEf0123456789";

describe("safeShareUrl", () => {
  it("accepte les adresses http(s) et refuse le reste", () => {
    expect(safeShareUrl(` ${URL} `)).toBe(URL);
    expect(safeShareUrl("http://192.168.1.20:8080/apps/cospend/s/x")).toBe(
      "http://192.168.1.20:8080/apps/cospend/s/x",
    );
    for (const bad of ["", "   ", "javascript:alert(1)", "data:text/html,x", "cospend://x", "pas une adresse", 42, null, undefined]) {
      expect(safeShareUrl(bad)).toBeNull();
    }
  });
});

describe("cospendAppLink", () => {
  it("construit le lien d'import des applications mobiles", () => {
    expect(cospendAppLink(URL)).toBe("cospend://cloud.example.org/AbCdEf0123456789/no-pass");
    expect(cospendAppLink("https://cloud.example.org/index.php/apps/cospend/s/Tok/")).toBe(
      "cospend://cloud.example.org/Tok/no-pass",
    );
    expect(cospendAppLink("https://example.org:8443/nextcloud/apps/cospend/s/Tok")).toBe(
      "cospend://example.org:8443/nextcloud/Tok/no-pass",
    );
  });

  it("refuse ce qui n'est pas un lien de partage Cospend en https", () => {
    expect(cospendAppLink("http://cloud.example.org/apps/cospend/s/Tok")).toBeNull();
    expect(cospendAppLink("https://cloud.example.org/apps/cospend/p/teste")).toBeNull();
    expect(cospendAppLink("https://cloud.example.org/")).toBeNull();
    expect(cospendAppLink("n'importe quoi")).toBeNull();
  });
});

describe("qrMatrix", () => {
  it("produit un chemin et une zone de silence de 4 modules", () => {
    const { size, path } = qrMatrix(URL);
    expect(size).toBeGreaterThan(8 + 20);
    expect(path.startsWith("M")).toBe(true);
    // Aucun module sombre dans la zone de silence.
    const coords = [...path.matchAll(/M(\d+) (\d+)h1v1h-1z/g)].map((m) => [Number(m[1]), Number(m[2])]);
    expect(coords.length).toBeGreaterThan(100);
    for (const [x, y] of coords) {
      expect(x).toBeGreaterThanOrEqual(4);
      expect(y).toBeGreaterThanOrEqual(4);
      expect(x).toBeLessThan(size - 4);
      expect(y).toBeLessThan(size - 4);
    }
  });

  it("est déterministe", () => {
    expect(qrMatrix(URL)).toEqual(qrMatrix(URL));
    expect(qrMatrix(URL).path).not.toBe(qrMatrix(URL + "2").path);
  });
});

type Dialog = HTMLElement & {
  hass?: HassLike;
  url: string;
  name: string;
  updateComplete: Promise<boolean>;
};

async function open(url: string, name = "Voyage"): Promise<Dialog> {
  const dialog = document.createElement("cospend-share-dialog") as Dialog;
  dialog.hass = { language: "fr" } as unknown as HassLike;
  dialog.url = url;
  dialog.name = name;
  document.body.append(dialog);
  await dialog.updateComplete;
  return dialog;
}

describe("cospend-share-dialog", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("affiche par défaut le lien de l'application, le lien web et un lien d'ouverture sûr", async () => {
    const dialog = await open(URL);
    const root = dialog.shadowRoot!;
    expect(root.querySelector("svg.qr path")).not.toBeNull();
    expect((root.querySelector("input.link") as HTMLInputElement).value).toBe(
      "cospend://cloud.example.org/AbCdEf0123456789/no-pass",
    );
    const link = root.querySelector("a.open") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe(URL);
    expect(link.rel).toContain("noopener");
    expect(root.textContent).toContain("Cowspent");
    expect(root.querySelectorAll("button.mode")).toHaveLength(2);
    expect(root.textContent).toContain("Voyage");
  });

  it("bascule sur le lien de la page web", async () => {
    const dialog = await open(URL);
    const root = dialog.shadowRoot!;
    const before = root.querySelector("svg.qr path")!.getAttribute("d");
    (root.querySelectorAll("button.mode")[1] as HTMLElement).click();
    await dialog.updateComplete;
    expect((root.querySelector("input.link") as HTMLInputElement).value).toBe(URL);
    expect(root.querySelector("svg.qr path")!.getAttribute("d")).not.toBe(before);
    expect(root.textContent).toContain("appareil photo");
  });

  it("sans lien d'application possible (http), seul le lien web est proposé", async () => {
    const dialog = await open("http://192.168.1.20:8080/apps/cospend/s/Tok");
    const root = dialog.shadowRoot!;
    expect(root.querySelectorAll("button.mode")).toHaveLength(0);
    expect((root.querySelector("input.link") as HTMLInputElement).value).toBe(
      "http://192.168.1.20:8080/apps/cospend/s/Tok",
    );
  });

  it("refuse un lien qui n'est pas une adresse web", async () => {
    const dialog = await open("javascript:alert(1)");
    const root = dialog.shadowRoot!;
    expect(root.querySelector("svg.qr")).toBeNull();
    expect(root.querySelector("a.open")).toBeNull();
    expect(root.querySelector("[role=alert]")).not.toBeNull();
  });

  it("copie le lien", async () => {
    let copied = "";
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text: string) => void (copied = text) },
    });
    const dialog = await open(URL);
    (dialog.shadowRoot!.querySelector("button.copy") as HTMLElement).click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await dialog.updateComplete;
    expect(copied).toBe("cospend://cloud.example.org/AbCdEf0123456789/no-pass");
    expect(dialog.shadowRoot!.querySelector("button.copy")!.textContent).toContain("Copié");
  });

  it("se ferme avec Échap, le bouton ou le fond", async () => {
    const dialog = await open(URL);
    let closed = 0;
    dialog.addEventListener("closed", () => closed++);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    (dialog.shadowRoot!.querySelector("button.close") as HTMLElement).click();
    const backdrop = dialog.shadowRoot!.querySelector(".backdrop") as HTMLElement;
    backdrop.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(closed).toBe(3);
  });
});
