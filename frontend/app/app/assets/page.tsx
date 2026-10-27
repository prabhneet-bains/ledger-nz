"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { usePeriod } from "@/components/PeriodFilter";
import { apiGet, apiSend, money } from "@/lib/api";
import { withPeriod } from "@/lib/period";

type Preset = {
  asset_class: string;
  label: string;
  diminishing_value: string;
  straight_line: string;
  authority: string;
};

type Asset = {
  asset_id: string;
  asset_name: string;
  asset_class: string;
  purchase_date: string;
  original_cost: string;
  depreciation_method: string;
  depreciation_rate: string;
  depreciation_claim: string;
  adjusted_tax_value: string;
  business_use_percentage: string;
  business_use_source: string;
  months: number;
  low_value_writeoff: boolean;
};

const CLASSES = [
  { id: "passenger_vehicle", label: "Passenger vehicle" },
  { id: "computer", label: "Computer" },
  { id: "office_furniture", label: "Office furniture" },
  { id: "other", label: "Other asset" },
];

export default function AssetsPage() {
  const period = usePeriod();
  const [rows, setRows] = useState<Asset[]>([]);
  const [year, setYear] = useState({ start: "", end: "" });
  const [presets, setPresets] = useState<Preset[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    asset_name: "",
    asset_class: "passenger_vehicle",
    purchase_date: "",
    original_cost: "",
    depreciation_method: "Diminishing_Value",
    depreciation_rate: "30",
    business_use_percentage: "100",
  });

  const preset = presets.find((item) => item.asset_class === form.asset_class);
  const lockedRate = preset ? (form.depreciation_method === "Straight_Line" ? preset.straight_line : preset.diminishing_value) : "";

  async function load() {
    if (!period.start || !period.end || period.start > period.end) return;
    const [listed, rates] = await Promise.all([
      apiGet<{ financial_year: { start: string; end: string }; assets: Asset[] }>(withPeriod("/assets", period)),
      apiGet<{ presets: Preset[] }>("/assets/rates"),
    ]);
    setRows(listed.assets);
    setYear(listed.financial_year);
    setPresets(rates.presets);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period.start, period.end]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await apiSend("/assets", "POST", {
        ...form,
        original_cost: Number(form.original_cost),
        depreciation_rate: Number(lockedRate || form.depreciation_rate),
        business_use_percentage: Number(form.business_use_percentage),
      });
      setForm((current) => ({ ...current, asset_name: "", original_cost: "" }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the asset");
    }
  }

  return (
    <AppShell>
      <h1>Assets and depreciation</h1>
      <p className="hint">
        A passenger vehicle is depreciated at 30% diminishing value or 21% straight line. Fuel, repairs, registration and insurance stay as
        Motor Vehicle expenses. Anything costing $1,000 or less (GST exclusive) is deducted in the year you buy it.
        {year.start ? ` Claims below follow the date range, ${year.start} to ${year.end}.` : ""}
      </p>
      {error ? <p className="error">{error}</p> : null}
      <form className="card row" onSubmit={onSubmit} style={{ marginTop: 16 }}>
        <label>
          Asset
          <input value={form.asset_name} onChange={(e) => setForm({ ...form, asset_name: e.target.value })} required />
        </label>
        <label>
          Class
          <select
            value={form.asset_class}
            onChange={(e) => setForm({ ...form, asset_class: e.target.value })}
          >
            {CLASSES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Purchase date
          <input type="date" value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} required />
        </label>
        <label>
          Cost (GST exclusive)
          <input value={form.original_cost} onChange={(e) => setForm({ ...form, original_cost: e.target.value })} required />
        </label>
        <label>
          Method
          <select
            value={form.depreciation_method}
            onChange={(e) => setForm({ ...form, depreciation_method: e.target.value })}
          >
            <option value="Diminishing_Value">Diminishing value</option>
            <option value="Straight_Line">Straight line</option>
          </select>
        </label>
        <label>
          Rate %
          <input
            value={lockedRate || form.depreciation_rate}
            onChange={(e) => setForm({ ...form, depreciation_rate: e.target.value })}
            readOnly={Boolean(preset)}
          />
        </label>
        <label>
          Business use %
          <input
            type="number"
            min={0}
            max={100}
            value={form.business_use_percentage}
            onChange={(e) => setForm({ ...form, business_use_percentage: e.target.value })}
          />
        </label>
        <button className="btn">Add</button>
      </form>
      {preset ? <p className="hint">{preset.authority}</p> : null}
      <article className="card table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              <th>Asset</th>
              <th>Purchased</th>
              <th>Cost</th>
              <th>This year</th>
              <th>Business use</th>
              <th>Adjusted tax value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.asset_id}>
                <td>{row.asset_name}</td>
                <td>{row.purchase_date}</td>
                <td>{money(row.original_cost)}</td>
                <td>
                  {row.low_value_writeoff ? "Immediate deduction" : `${row.depreciation_method === "Straight_Line" ? "SL" : "DV"} ${row.depreciation_rate}%`}
                  <div className="hint">{money(row.depreciation_claim)} · {row.months} months</div>
                </td>
                <td>
                  {row.business_use_percentage}%{row.business_use_source === "logbook" ? " from the logbook" : ""}
                </td>
                <td>{money(row.adjusted_tax_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? <p className="hint">No assets yet.</p> : null}
      </article>
    </AppShell>
  );
}
