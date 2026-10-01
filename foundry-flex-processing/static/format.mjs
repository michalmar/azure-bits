export function duration(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const milliseconds = Number(value);
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(2)} s` : `${milliseconds.toFixed(0)} ms`;
}

export function money(value, currency = "USD") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const amount = Number(value);
  const digits = amount < 0.01 ? 6 : 4;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount);
}

export function tokenCount(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

export function phaseWidths(latency) {
  const phases = [
    Math.max(Number(latency.authenticationMs || 0), 0),
    Math.max(Number(latency.requestToHeadersMs || 0), 0),
    Math.max(Number(latency.headersToFirstTokenMs || 0), 0),
    Math.max(Number(latency.generationMs || 0), 0),
  ];
  const total = phases.reduce((sum, value) => sum + value, 0) || 1;
  return phases.map((value) => `${Math.max((value / total) * 100, value ? 2 : 0).toFixed(2)}%`);
}
