"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiGet, apiSend } from "@/lib/api";
import { Account } from "@/lib/types";

export default function AccountsPage() {
  const [rows, setRows] = useState<Account[]>([]);
  const [form, setForm] = useState({
    account_name: "",
    account_type: "Expense",
    tax_rate: "15",
    business_claim_percentage: "100",
  });
  const [error, setError] = useState("");

  async function load() {
    setRows(await apiGet<Account[]>("/accounts"));
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      await apiSend("/accounts", "POST", {
        ...form,
        tax_rate: Number(form.tax_rate),
        business_claim_percentage: Number(form.business_claim_percentage),
      });
      setForm({ ...form, account_name: "" });
      setError("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create account");
    }
  }

  return (
    <AppShell>
      <h1>Chart of accounts</h1>
      <p className="hint">
        Business use % is the default share of an expense account that is deductible. Home Office is already 50%. Change one bill on Review
        or Transactions when that payment is different.
      </p>
      {error ? <p className="error">{error}</p> : null}
      <form className="card row" onSubmit={onSubmit}>
        <label>
          Name
          <input value={form.account_name} onChange={(e) => setForm({ ...form, account_name: e.target.value })} required />
        </label>
        <label>
          Type
          <select value={form.account_type} onChange={(e) => setForm({ ...form, account_type: e.target.value })}>
            {["Income", "Expense", "Asset", "Liability", "Equity"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label>
          Tax rate %
          <input value={form.tax_rate} onChange={(e) => setForm({ ...form, tax_rate: e.target.value })} />
        </label>
        <label>
          Business use %
          <input
            value={form.business_claim_percentage}
            onChange={(e) => setForm({ ...form, business_claim_percentage: e.target.value })}
          />
        </label>
        <button className="btn">Add account</button>
      </form>
      <article className="card table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>GST %</th>
              <th>Claim %</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.account_id}>
                <td>{row.account_name}</td>
                <td>{row.account_type}</td>
                <td>{row.tax_rate}</td>
                <td>{row.business_claim_percentage}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </AppShell>
  );
}
