// Aperçu du montant saisi : « 12,5 + 7 » donne 19,5. Le serveur reste juge de l'expression.

/** Évalue + - * / et parenthèses (virgule ou point décimal) ; ``null`` si l'expression est invalide. */
export function evaluateAmount(text: string): number | null {
  const source = text.replace(/\s+/g, "").replace(/,/g, ".");
  if (!source || !/^[0-9+\-*/().]+$/.test(source)) return null;
  let position = 0;

  const factor = (): number => {
    const char = source[position];
    if (char === "-") {
      position++;
      return -factor();
    }
    if (char === "+") {
      position++;
      return factor();
    }
    if (char === "(") {
      position++;
      const value = expression();
      if (source[position] !== ")") throw new Error("parenthèse");
      position++;
      return value;
    }
    const number = /^(\d+(\.\d*)?|\.\d+)/.exec(source.slice(position));
    if (!number) throw new Error("nombre");
    position += number[0].length;
    return parseFloat(number[0]);
  };

  const term = (): number => {
    let value = factor();
    while (source[position] === "*" || source[position] === "/") {
      const operator = source[position++];
      const right = factor();
      value = operator === "*" ? value * right : value / right;
    }
    return value;
  };

  const expression = (): number => {
    let value = term();
    while (source[position] === "+" || source[position] === "-") {
      const operator = source[position++];
      const right = term();
      value = operator === "+" ? value + right : value - right;
    }
    return value;
  };

  try {
    const value = expression();
    if (position !== source.length || !Number.isFinite(value)) return null;
    return Math.round(value * 100) / 100;
  } catch {
    return null;
  }
}
