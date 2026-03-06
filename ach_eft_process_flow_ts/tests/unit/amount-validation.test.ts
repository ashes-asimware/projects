import assert from "node:assert";
import { describe, it } from "node:test";
import { isPositiveFiniteAmount } from "../support/amount-validation";

describe("isPositiveFiniteAmount", () => {
  it("validates positive finite numbers", () => {
    assert.ok(isPositiveFiniteAmount({ amount: 1 }));
    assert.ok(!isPositiveFiniteAmount({ amount: 0 }));
    assert.ok(!isPositiveFiniteAmount({ amount: -5 }));
    assert.ok(!isPositiveFiniteAmount({ amount: Infinity }));
    assert.ok(!isPositiveFiniteAmount({}));
    assert.ok(!isPositiveFiniteAmount({ amount: Number.NaN }));
  });
});
