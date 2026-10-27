"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { usePeriod } from "@/components/PeriodFilter";
import { apiGet, apiSend } from "@/lib/api";
import { withPeriod } from "@/lib/period";

type LogRow = {
  log_id: string;
  date: string;
  odometer_start: number;
  odometer_end: number;
  distance: number;
  purpose: string;
  notes: string | null;
};

type BulkRow = { date: string; odometer_end: string; purpose: "Business" | "Personal"; notes: string };

export default function LogbookPage() {
  const period = usePeriod();
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [nextStart, setNextStart] = useState<number | null>(null);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [end, setEnd] = useState("");
  const [purpose, setPurpose] = useState<"Business" | "Personal">("Business");
  const [notes, setNotes] = useState("");
  const [bulk, setBulk] = useState<BulkRow[]>([
    { date: new Date().toISOString().slice(0, 10), odometer_end: "", purpose: "Business", notes: "" },
  ]);
  const [error, setError] = useState("");

  async function load() {
    if (!period.start || !period.end || period.start > period.end) return;
    const data = await apiGet<{ logs: LogRow[]; next_odometer_start: number | null }>(withPeriod("/logbook", period));
    setLogs(data.logs);
    setNextStart(data.next_odometer_start);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period.start, period.end]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await apiSend("/logbook", "POST", {
        date,
        odometer_end: Number(end),
        purpose,
        notes,
      });
      setEnd("");
      setNotes("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function onBulk(event: FormEvent) {
    event.preventDefault();
    try {
      await apiSend("/logbook/bulk", "POST", {
        entries: bulk
          .filter((row) => row.odometer_end)
          .map((row) => ({
            date: row.date,
            odometer_end: Number(row.odometer_end),
            purpose: row.purpose,
            notes: row.notes || null,
          })),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk save failed");
    }
  }

  const businessKm = logs.filter((l) => l.purpose === "Business").reduce((s, l) => s + l.distance, 0);
  const personalKm = logs.filter((l) => l.purpose === "Personal").reduce((s, l) => s + l.distance, 0);
  const bulkStarts: Array<number | null> = [];
  let cursor = nextStart;
  for (const row of bulk) {
    bulkStarts.push(cursor);
    if (row.odometer_end) cursor = Number(row.odometer_end);
  }

  return (
    <AppShell>
      <h1>Vehicle logbook</h1>
      <p className="hint">
        Next start odometer: <strong>{nextStart ?? "set on first trip"}</strong>. Designed for one-thumb entry on a phone.
      </p>
      {error ? <p className="error">{error}</p> : null}
      <section className="grid cards" style={{ marginTop: 12 }}>
        <article className="card">
          <h3>Business km</h3>
          <p className="metric serif">{businessKm}</p>
        </article>
        <article className="card">
          <h3>Personal km</h3>
          <p className="metric serif">{personalKm}</p>
        </article>
      </section>
      <form className="card logbook-form grid" onSubmit={onSubmit} style={{ marginTop: 16 }}>
        <div className="row">
          <label>
            Date
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </label>
          <label>
            Odometer start
            <input value={nextStart ?? ""} readOnly />
          </label>
          <label>
            Odometer end
            <input inputMode="numeric" value={end} onChange={(e) => setEnd(e.target.value)} required />
          </label>
          <label>
            Purpose
            <select value={purpose} onChange={(e) => setPurpose(e.target.value as "Business" | "Personal")}>
              <option>Business</option>
              <option>Personal</option>
            </select>
          </label>
        </div>
        <label>
          Notes
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Client visit, home, etc." />
        </label>
        <button className="btn" type="submit">
          Save trip
        </button>
      </form>
      <form className="card" onSubmit={onBulk} style={{ marginTop: 16 }}>
        <h2>Bulk weekend catch-up</h2>
        <p className="hint">Each row starts where the previous one ended. The first row uses the latest odometer.</p>
        {bulk.map((row, index) => (
          <div className="row" key={index} style={{ marginBottom: 8 }}>
            <label>
              Date
              <input
                type="date"
                value={row.date}
                onChange={(e) => {
                  const next = [...bulk];
                  next[index] = { ...row, date: e.target.value };
                  setBulk(next);
                }}
              />
            </label>
            <label>
              Start
              <input value={bulkStarts[index] ?? ""} readOnly />
            </label>
            <label>
              End km
              <input
                inputMode="numeric"
                value={row.odometer_end}
                onChange={(e) => {
                  const next = [...bulk];
                  next[index] = { ...row, odometer_end: e.target.value };
                  setBulk(next);
                }}
              />
            </label>
            <label>
              Purpose
              <select
                value={row.purpose}
                onChange={(e) => {
                  const next = [...bulk];
                  next[index] = { ...row, purpose: e.target.value as "Business" | "Personal" };
                  setBulk(next);
                }}
              >
                <option>Business</option>
                <option>Personal</option>
              </select>
            </label>
          </div>
        ))}
        <div className="row">
          <button
            className="btn secondary"
            type="button"
            onClick={() => setBulk([...bulk, { date: date, odometer_end: "", purpose: "Business", notes: "" }])}
          >
            Add row
          </button>
          <button className="btn" type="submit">
            Save bulk
          </button>
        </div>
      </form>
      <article className="card table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Start</th>
              <th>End</th>
              <th>Km</th>
              <th>Purpose</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((row) => (
              <tr key={row.log_id}>
                <td>{row.date}</td>
                <td>{row.odometer_start}</td>
                <td>{row.odometer_end}</td>
                <td>{row.distance}</td>
                <td>{row.purpose}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </AppShell>
  );
}
