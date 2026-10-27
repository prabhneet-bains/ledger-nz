export type PeriodPreset = "this-month" | "previous-month" | "this-fy" | "previous-fy" | "custom";

export type Period = {
  preset: PeriodPreset;
  start: string;
  end: string;
};

export const PERIOD_PRESETS: { id: PeriodPreset; label: string }[] = [
  { id: "this-month", label: "This month" },
  { id: "previous-month", label: "Previous month" },
  { id: "this-fy", label: "This financial year" },
  { id: "previous-fy", label: "Previous financial year" },
  { id: "custom", label: "Custom" },
];

const STORAGE_KEY = "ledger-nz-period";
export const PERIOD_EVENT = "ledger-period";

function iso(day: Date): string {
  const month = String(day.getMonth() + 1).padStart(2, "0");
  const date = String(day.getDate()).padStart(2, "0");
  return `${day.getFullYear()}-${month}-${date}`;
}

/** NZ tax year runs 1 April to 31 March. offsetYears -1 is the previous year. */
export function financialYear(today: Date, offsetYears = 0): { start: string; end: string } {
  const yearEnding = (today.getMonth() >= 3 ? today.getFullYear() + 1 : today.getFullYear()) + offsetYears;
  return { start: `${yearEnding - 1}-04-01`, end: `${yearEnding}-03-31` };
}

export function monthRange(today: Date, offsetMonths: number): { start: string; end: string } {
  const first = new Date(today.getFullYear(), today.getMonth() + offsetMonths, 1);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
  return { start: iso(first), end: iso(last) };
}

export function rangeFor(preset: PeriodPreset, today = new Date(), custom?: { start: string; end: string }): Period {
  if (preset === "this-month") return { preset, ...monthRange(today, 0) };
  if (preset === "previous-month") return { preset, ...monthRange(today, -1) };
  if (preset === "previous-fy") return { preset, ...financialYear(today, -1) };
  if (preset === "custom") {
    const start = custom?.start || "";
    const end = custom?.end || "";
    return { preset, start, end };
  }
  return { preset, ...financialYear(today, 0) };
}

export function defaultPeriod(today = new Date()): Period {
  return rangeFor("this-fy", today);
}

export function loadPeriod(): Period {
  if (typeof window === "undefined") return defaultPeriod();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultPeriod();
    const saved = JSON.parse(raw) as Partial<Period>;
    const preset = PERIOD_PRESETS.some((item) => item.id === saved.preset) ? (saved.preset as PeriodPreset) : "this-fy";
    if (preset === "custom") return rangeFor("custom", new Date(), { start: saved.start || "", end: saved.end || "" });
    return rangeFor(preset);
  } catch {
    return defaultPeriod();
  }
}

export function savePeriod(period: Period) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(period));
  window.dispatchEvent(new Event(PERIOD_EVENT));
}

export function withPeriod(path: string, period: Period, extra?: Record<string, string>): string {
  const params = new URLSearchParams();
  if (period.start) params.set("start", period.start);
  if (period.end) params.set("end", period.end);
  if (extra) {
    for (const [key, value] of Object.entries(extra)) params.set(key, value);
  }
  const query = params.toString();
  if (!query) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${query}`;
}

export function formatPeriod(period: Period): string {
  if (!period.start || !period.end) return "Choose a start and end date";
  const fmt = new Intl.DateTimeFormat("en-NZ", { day: "numeric", month: "short", year: "numeric" });
  const start = fmt.format(new Date(`${period.start}T00:00:00`));
  const end = fmt.format(new Date(`${period.end}T00:00:00`));
  return `${start} – ${end}`;
}
