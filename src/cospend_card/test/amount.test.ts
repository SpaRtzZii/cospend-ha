import { describe, expect, it } from "vitest";

import { evaluateAmount } from "../src/amount";

describe("evaluateAmount", () => {
  it.each([
    ["12", 12],
    ["12,5", 12.5],
    ["12.5 + 7", 19.5],
    ["12,5+7", 19.5],
    ["2 * (3 + 4)", 14],
    ["10 / 4", 2.5],
    ["-5 + 8", 3],
    ["10 / 3", 3.33],
    ["1,5 + 2,5", 4],
  ])("%s vaut %s", (text, expected) => {
    expect(evaluateAmount(text)).toBe(expected);
  });

  it.each(["", "abc", "12 +", "(1 + 2", "1 / 0", "2 ** 3", "1;2", "12 euros"])(
    "refuse %j",
    (text) => {
      expect(evaluateAmount(text)).toBeNull();
    },
  );
});
