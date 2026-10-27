"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { usePeriod } from "@/components/PeriodFilter";
import { apiGet, apiSend, money } from "@/lib/api";
import { withPeriod } from "@/lib/period";

type Gst = { output_gst: string; input_gst: string; gst_to_pay: string; start: string; end: string };
type Hist = {
  record_id: string;
  period_type: string;
  start_date: string;
  end_date: string;
  total_income: string;
  tax_paid: string;
};

export default function TaxPage() {
  const period = usePeriod();
  const [gst, setGst] = useState<Gst | null>(null);
  const [history, setHistory] = useState<Hist[]>([]);
  const [form, setForm] = useState({
    period_type: "GST",
    start_date: "",
    end_date: "",
    total_income: "",
    tax_paid: "",
  });

  async function loadSchedule() {
    if (!period.start || !period.end || period.start > period.end) return;
    setGst(await apiGet<Gst>(withPeriod("/dashboard/gst", period)));
    setHistory(await apiGet<Hist[]>("/tax/history"));
  }

  useEffect(() => {
    loadSchedule().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period.start, period.end]);

  async function addHistory(event: FormEvent) {
    event.preventDefault();
    await apiSend("/tax/history", "POST", {
      ...form,
      total_income: Number(form.total_income),
      tax_paid: Number(form.tax_paid),
    });
    await loadSchedule();
  }

  return (
    <AppShell>
      <h1>GST &amp; tax records</h1>
      <p className="hint">GST below uses the date range at the top of the page.</p>
      <section className="grid cards" style={{ marginTop: 16 }}>
        <article className="card">
          <h3>Output GST</h3>
          <p className="metric serif">{money(gst?.output_gst)}</p>
        </article>
        <article className="card">
          <h3>Input GST</h3>
          <p className="metric serif">{money(gst?.input_gst)}</p>
        </article>
        <article className="card">
          <h3>GST to pay</h3>
          <p className="metric serif">{money(gst?.gst_to_pay)}</p>
        </article>
      </section>
      <form className="card" onSubmit={addHistory} style={{ marginTop: 16 }}>
        <h2>File an IRD historical row</h2>
        <div className="row">
          <label>
            Type
            <select value={form.period_type} onChange={(e) => setForm({ ...form, period_type: e.target.value })}>
              <option>GST</option>
              <option>IncomeTax</option>
            </select>
          </label>
          <label>
            Start
            <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} required />
          </label>
          <label>
            End
            <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} required />
          </label>
          <label>
            Total income
            <input value={form.total_income} onChange={(e) => setForm({ ...form, total_income: e.target.value })} required />
          </label>
          <label>
            Tax paid
            <input value={form.tax_paid} onChange={(e) => setForm({ ...form, tax_paid: e.target.value })} required />
          </label>
          <button className="btn">Save</button>
        </div>
      </form>
      <article className="card table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>Period</th>
              <th>Income</th>
              <th>Tax paid</th>
            </tr>
          </thead>
          <tbody>
            {history.map((row) => (
              <tr key={row.record_id}>
                <td>{row.period_type}</td>
                <td>
                  {row.start_date} → {row.end_date}
                </td>
                <td>{money(row.total_income)}</td>
                <td>{money(row.tax_paid)}</td>
              </tr>
            ))}
          </tbody>
        </tab