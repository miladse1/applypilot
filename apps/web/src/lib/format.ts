export function postedLabel(days: number | null | undefined, discovered?: string | null) {
  if (days === null || days === undefined) {
    if (!discovered) return "Date not listed";
    const found = Math.max(0, Math.round((Date.now() - new Date(discovered).getTime()) / 86400000));
    return found === 0 ? "Found today" : `Found ${found}d ago`;
  }
  if (days === 0) return "Posted today";
  if (days === 1) return "Posted yesterday";
  if (days < 30) return `Posted ${days}d ago`;
  const months = Math.round(days / 30);
  return `Posted ${months} mo ago`;
}

export function dateLabel(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

export function fullDate(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function salaryLabel(min: number | null, max: number | null, currency: string | null) {
  if (!min) return "";
  const symbol = currency === "USD" ? "US$" : "$";
  const fmt = (value: number) => (value >= 1000 ? `${Math.round(value / 1000)}k` : `${value}`);
  const range = max ? `${fmt(min)}–${fmt(max)}` : `${fmt(min)}+`;
  return `${symbol}${range}${min < 300 ? "/hr" : ""}`;
}

export function titleCase(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function stripMarkup(text: string) {
  return text.replace(/\*\*(.+?)\*\*/g, "$1");
}

export function plural(count: number, word: string, pluralWord?: string) {
  return `${count} ${count === 1 ? word : pluralWord || `${word}s`}`;
}
