const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "TRY",
  currencyDisplay: "narrowSymbol",
  minimumFractionDigits: 2,
});
const compact = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
});
export const money = (value: number) => currency.format(value);
export const signedMoney = (value: number) =>
  `${value >= 0 ? "+" : "−"}${money(Math.abs(value))}`;
export const percent = (value: number, signed = false, digits = 2) =>
  `${signed && value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
export const shortNumber = (value: number) => compact.format(value);
export const pnlPercent = (entry: number, current: number) =>
  (current / entry - 1) * 100;
export const dateLabel = (date: string) =>
  new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${date}T12:00:00Z`));
