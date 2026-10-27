"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { usePeriod } from "@/components/PeriodFilter";
import { apiGet, apiSend, money } from "@/lib/api";
import { withPeriod } from "@/lib/period";
import { Account, Transaction } from "@/lib/types";

const ACCOUNT_ORDER = ["Income", "Expense", "Equity", "Asset", "Liability"];

type Prompt = {
  row: Transaction;
  accountId: string;
  accountName: string;
  claim: string;
  similar: Transaction[];
};

export default function ReviewPage() {
  const period = usePeriod();
  const [rows, setRows] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!period.start || !period.end || period.start > period.end) return;
    try {
      const [tx, accts] = await Promise.all([
        apiGet<Transaction[]>(withPeriod("/transactions", period, { status: "Pending_Review", limit: "500" })),
        apiGet<Account[]>("/accounts"),
      ]);
      setRows(tx);
      setAccounts(accts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period.start, period.end]);

  async function reconcileOne(row: Transaction, accountId: string, claim: string) {
    await apiSend(`/transactions/${row.transaction_id}`, "PATCH", {
      account_id: accountId,
      status: "Reconciled",
      business_claim_percentage: Number(claim),
    });
    setPrompt(null);
    await load();
  }

  async function reconcileAll(current: Prompt) {
    await apiSend("/transactions/bulk-code", "POST", {
      account_id: current.accountId,
      transaction_ids: [current.row.transaction_id, ...current.similar.map((row) => row.transaction_id)],
      remember_payee: true,
      business_claim_percentage: Number(current.claim),
    });
    setPrompt(null);
    await load();
  }

  async function capitalise(row: Transaction, claim: string) {
    setBusy(true);
    setError("");
    try {
      await apiSend("/assets/capitalise", "POST", {
        transaction_id: row.transaction_id,
        asset_name: row.payee || "Passenger vehicle",
        business_use_percentage: Number(claim || "100"),
        depreciation_method: "Diminishing_Value",
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not depreciate this vehicle");
    } finally {
      setBusy(false);
    }
  }

  async function approve(row: Transaction, accountId: string, claim: string) {
    setBusy(true);
    setError("");
    try {
      const direction = Number(row.gross_amount) > 0 ? "in" : "out";
      const similar = await apiGet<Transaction[]>(
        withPeriod("/transactions/similar", period, {
          payee: row.payee || "",
          direction,
          exclude: row.transaction_id,
        }),
      );
      if (similar.length === 0) {
        await reconcileOne(row, accountId, claim);
        return;
      }
      const account = accounts.find((item) => item.account_id === accountId);
      setPrompt({ row, accountId, accountName: account?.account_name || "this category", claim, similar });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reconcile");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <h1>Human review queue</h1>
      <p className="hint">
        Client fees go to Consulting Fees. Other money in goes to Other Income. Personal spending from this account goes to Drawings,
        so it stays out of profit and GST. For a mixed expense, set business use % — Home Office starts at 50% — and only that share is deducted.
      </p>
      {error ? <p className="error">{error}</p> : null}
      {prompt ? (
        <article className="card" style={{ marginTop: 16 }}>
          <h2>
            {prompt.similar.length + 1} lines from {prompt.row.payee || "this payee"}
          </h2>
          <p>
            Mark all of these as <strong>{prompt.accountName}</strong>
            {Number(prompt.claim) < 100 ? ` at ${prompt.claim}% business use` : ""}? Future lines from this payee will use the same category.
          </p>
          <ul>
            <li>
              {prompt.row.date} · {money(prompt.row.gross_amount)} · {prompt.row.description}
            </li>
            {prompt.similar.map((row) => (
              <li key={row.transaction_id}>
                {row.date} · {money(row.gross_amount)} · {row.description}
              </li>
            ))}
          </ul>
          <div className="row">
            <button className="btn secondary" type="button" disabled={busy} onClick={() => setPrompt(null)}>
              Cancel
            </button>
            <button
              className="btn secondary"
              type="button"
              disabled={busy}
              onClick={() => reconcileOne(prompt.row, prompt.accountId, prompt.claim).catch((err) => setError(err.message))}
            >
              This line only
            </button>
            <button
              className="btn"
              type="button"
              disabled={busy}
              onClick={() => reconcileAll(prompt).catch((err) => setError(err.message))}
            >
              Mark all and remember
            </button>
          </div>
        </article>
      ) : null}
      <article className="card table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Payee</th>
              <th>Gross</th>
              <th>Recode</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <ReviewRow key={row.transaction_id} row={row} accounts={accounts} busy={busy} onApprove={approve} onCapitalise={capitalise} />
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? <p className="hint">Nothing waiting.</p> : null}
      </article>
    </AppShell>
  );
}

function ReviewRow({
  row,
  accounts,
  busy,
  onApprove,
  onCapitalise,
}: {
  row: Transaction;
  accounts: Account[];
  busy: boolean;
  onApprove: (row: Transaction, accountId: string, claim: string) => Promise<void>;
  onCapitalise: (row: Transaction, claim: string) => Promise<void>;
}) {
  const [accountId, setAccountId] = useState(row.account_id || "");
  const selected = accounts.find((account) => account.account_id === accountId);
  const [claim, setClaim] = useState(selected?.account_type === "Expense" ? String(selected.business_claim_percentage) : "100");
  const grouped = ACCOUNT_ORDER.map((type) => ({
    type,
    accounts: accounts.filter((account) => account.account_type === type),
  })).filter((group) => group.accounts.length > 0);
  return (
    <tr>
      <td>{row.date}</td>
      <td>{row.payee || row.description}</td>
      <td>{money(row.gross_amount)}</td>
      <td>
        <select
          value={accountId}
          onChange={(e) => {
            const next = e.target.value;
            setAccountId(next);
            const account = accounts.find((item) => item.account_id === next);
            setClaim(account?.account_type === "Expense" ? String(account.business_claim_percentage) : "100");
          }}
        >
          <option value="">Choose account</option>
          {grouped.map((group) => (
            <optgroup key={group.type} label={group.type}>
              {group.accounts.map((account) => (
                <option key={account.account_id} value={account.account_id}>
                  {account.account_name}
                  {account.account_name === "Drawings" ? " — personal" : ""}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        {selected?.account_type === "Expense" ? (
          <label>
            Business use %
            <input type="number" min={0} max={100} step="1" value={claim} onChange={(e) => setClaim(e.target.value)} />
          </label>
        ) : null}
      </td>
      <td>
        {selected?.account_name === "Motor Vehicle" && Math.abs(Number(row.gross_amount)) > 1000 ? (
          <div className="row">
            <button className="btn" type="button" disabled={busy} onClick={() => onCapitalise(row, claim || "100")}>
              Depreciate at 30%
            </button>
            <button className="btn secondary" type="button" disabled={busy} onClick={() => onApprove(row, accountId, claim || "100")}>
              Running cost
            </button>
          </div>
        ) : (
          <button className="btn" type="button" disabled={!accountId || busy} onClick={() => onApprove(row, accountId, claim || "100")}>
            Reconcile
          </button>
        )}
      </td>
    </tr>
  );
}
