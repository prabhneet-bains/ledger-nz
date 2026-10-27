"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { usePeriod } from "@/components/PeriodFilter";
import { apiGet, apiSend, money } from "@/lib/api";
import { withPeriod } from "@/lib/period";
import { Account, Transaction } from "@/lib/types";

export default function TransactionsPage() {
  const period = usePeriod();
  const [rows, setRows] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    account_id: "",
    description: "",
    gross_amount: "",
  });

  async function load() {
    if (!period.start || !period.end || period.start > period.end) return;
    try {
      const [tx, accts] = await Promise.all([
        apiGet<Transaction[]>(withPeriod("/transactions", period, { limit: "500" })),
        apiGet<Account[]>("/accounts"),
      ]);
      setRows(tx);
      setAccounts(accts);
      if (!form.account_id && accts[0]) setForm((f) => ({ ...f, account_id: accts[0].account_id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period.start, period.end]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    try {
      await apiSend("/transactions", "POST", {
        ...form,
        gross_amount: Number(form.gross_amount),
        source: "AdHoc",
      });
      setForm((f) => ({ ...f, description: "", gross_amount: "" }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  return (
    <AppShell>
      <div className="top">
        <h1>Transactions</h1>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <form className="card row" onSubmit={onCreate}>
        <label>
          Date
          <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} required />
        </label>
        <label>
          Account
          <select value={form.account_id} onChange={(e) => setForm({ ...form, account_id: e.target.value })}>
            {accounts.map((account) => (
              <option key={account.account_id} value={account.account_id}>
                {account.account_type} · {account.account_name}
              </option>
            ))}
          </select>
        </label>
        <label style={{ flex: 1, minWidth: 180 }}>
          Description
          <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required />
        </label>
        <label>
          Gross (incl. GST)
          <input
            type="number"
            step="0.01"
            value={form.gross_amount}
            onChange={(e) => setForm({ ...form, gross_amount: e.target.value })}
            required
          />
        </label>
        <button className="btn" type="submit">
          Add
        </button>
      </form>
      <article className="card table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Payee</th>
              <th>Gross</th>
              <th>GST</th>
              <th>Net</th>
              <th>Business use</th>
              <th>Source</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.transaction_id}>
                <td>{row.date}</td>
                <td>
                  {row.payee || row.description}
                  {row.is_internal_transfer ? <div className="hint">Internal transfer</div> : null}
                </td>
                <td>{money(row.gross_amount)}</td>
                <td>{money(row.gst_amount)}</td>
                <td>{money(row.net_amount)}</td>
                <td>
                  <ClaimCell row={row} accounts={accounts} onSaved={load} />
                </td>
                <td>{row.source}</td>
                <td>
                  <span className={`badge ${row.status === "Reconciled" ? "ok" : row.status === "Ignored" ? "ignored" : "pending"}`}>
                    {row.status === "Pending_Review" ? "Review" : row.status === "Ignored" ? "Ignored" : "Reconciled"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </AppShell>
  );
}

function ClaimCell({ row, accounts, onSaved }: { row: Transaction; accounts: Account[]; onSaved: () => Promise<void> }) {
  const account = accounts.find((item) => item.account_id === row.account_id);
  const [claim, setClaim] = useState(String(row.business_claim_percentage ?? account?.business_claim_percentage ?? "100"));
  if (row.is_internal_transfer || account?.account_type !== "Expense") return <span>—</span>;
  return (
    <input
      type="number"
      min={0}
      max={100}
      step="1"
      value={claim}
      aria-label={`Business use for ${row.payee || row.description}`}
      style={{ width: 72 }}
      onChange={(e) => setClaim(e.target.value)}
      onBlur={async () => {
        const next = Number(claim);
        if (Number.isNaN(next) || String(row.business_claim_percentage ?? "") === claim) return;
        await apiSend(`/transactions/${row.transaction_id}`, "PATCH", {
          account_id: row.account_id,
          business_claim_percentage: next,
          status: row.status === "Pending_Review" ? "Reconciled" : row.status,
        });
        await onSaved();
      }}
    />
  );
}
