export const isPositiveFiniteAmount = (
  update: { amount?: unknown }
): update is { amount: number } =>
  typeof update.amount === "number" &&
  Number.isFinite(update.amount) &&
  update.amount > 0;
