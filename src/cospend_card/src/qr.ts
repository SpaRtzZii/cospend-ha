import qrcode from "qrcode-generator";

/** Un lien de partage valide : adresse http(s) uniquement (jamais ``javascript:`` ni autre schéma). */
export function safeShareUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text) return null;
  try {
    const url = new URL(text);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

export interface QrMatrix {
  /** Nombre de modules par côté (zone de silence comprise). */
  size: number;
  /** Chemin SVG des modules sombres, dans un repère où un module vaut 1. */
  path: string;
}

/** Calcule le QR code d'un texte (correction d'erreur moyenne) avec sa zone de silence. */
export function qrMatrix(text: string, quiet = 4): QrMatrix {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const count = qr.getModuleCount();
  const parts: string[] = [];
  for (let row = 0; row < count; row++) {
    for (let col = 0; col < count; col++) {
      if (qr.isDark(row, col)) parts.push(`M${col + quiet} ${row + quiet}h1v1h-1z`);
    }
  }
  return { size: count + 2 * quiet, path: parts.join("") };
}
