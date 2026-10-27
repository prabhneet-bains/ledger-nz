"use client";

import { useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { usePeriod } from "@/components/PeriodFilter";
import { apiGet, money } from "@/lib/api";
import { withPeriod } from "@/lib/period";
import { DashboardSummary } from "@/lib/types";

type Line = { account_name: string; net_amount: string };

export default function DashboardPage() {
  const period = usePeriod();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!period.start || !period.end || period.start > period.end) return;
    apiGet<DashboardSummary>(withPeriod("/dashboard/summary", period))
      .then(setData)
      .catch((err) => setError(err.message));
  }, [period]);

  const pnl = data?.pnl;
  const tax = pnl?.income_tax;
  const incomeLines = pnl?.income_lines || [];
  const expenseLines = pnl?.expense_lines || [];

  return (
    <AppShell>
      <div className="top">
        <div>
          <h1>Practice snapshot</h1>
          <p className="hint">
            Showing {data?.financial_year.start} → {data?.financial_year.end}. Transfers are excluded. Expenses use the business-use
            share only.
            {pnl?.uncoded_count ? ` ${pnl.uncoded_count} uncoded rows (${money(pnl.uncoded_gross)}) are waiting in review.` : ""}
          </p>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <section className="grid cards">
        <article className="card">
          <h3>Income</h3>
          <p className="metric serif">{money(pnl?.total_income)}</p>
        </article>
        <article className="card">
          <h3>Expenses</h3>
          <p className="metric serif">{money(pnl?.total_expense)}</p>
          <p className="hint">Private use excluded {money(pnl?.private_excluded)}</p>
        </article>
        <article className="card">
          <h3>Taxable profit</h3>
          <p className="metric serif">{money(pnl?.net_profit)}</p>
          <p className="hint">Income minus deductible expenses</p>
        </article>
        <article className="card">
          <h3>Income tax</h3>
          <p className="metric serif">{money(tax?.income_tax)}</p>
          <p className="hint">IRD individual rates. After tax {money(tax?.profit_after_tax)}</p>
        </article>
        <article className="card">
          <h3>GST collected</h3>
          <p className="metric serif">{money(data?.gst.output_gst)}</p>
          <p className="hint">Input claimed {money(data?.gst.input_gst)}</p>
        </article>
        <article className="card">
          <h3>GST to pay</h3>
          <p className="metric serif">{money(data?.gst.gst_to_pay)}</p>
        </article>
        <article className="card">
          <h3>Funds introduced</h3>
          <p className="metric serif">{money(pnl?.funds_introduced)}</p>
          <p className="hint">Drawings {money(pnl?.drawings)}</p>
        </article>
        <article className="card">
          <h3>Pending review</h3>
          <p className="metric serif">{data?.pending_review ?? "—"}</p>
        </article>
      </section>

      {pnl?.depreciation?.lines?.length ? (
        <article className="card" style={{ marginTop: 16 }}>
          <h2>Depreciation this year</h2>
          <p className="hint">
            Deducted {money(pnl.depreciation.total)}. A passenger vehicle uses 30% diminishing value. The logbook sets its business use when
            trips are recorded.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Rate</th>
                  <th>Months</th>
                  <th>Business use</th>
                  <th>Claim</th>
                  <th>Adjusted tax value</th>
                </tr>
              </thead>
              <tbody>
                {pnl.depreciation.lines.map((line) => (
                  <tr key={line.asset_name + line.depreciation_claim}>
                    <td>{line.asset_name}</td>
                    <td>
                      {line.low_value_writeoff ? "Immediate" : `${line.depreciation_method === "Straight_Line" ? "SL" : "DV"} ${line.depreciation_rate}%`}
                    </td>
                    <td>{line.months}</td>
                    <td>
                      {line.business_use_percentage}%{line.business_use_source === "logbook" ? " logbook" : ""}
                    </td>
                    <td>{money(line.depreciation_claim)}</td>
                    <td>{money(line.adjusted_tax_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}

      <div className="split">
        <CategoryCard title="Income by category" lines={incomeLines} empty="No income in this year yet." />
        <CategoryCard title="Expenses by category" lines={expenseLines} empty="No deductible expenses in this year yet." />
      </div>

      <div className="split">
        <article className="card">
          <h2>Income tax on this profit</h2>
          <p className="hint">
            Progressive IRD individual rates from 1 April 2025, applied to this practice&apos;s profit. Salary, ACC, and tax credits are not
            included.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Band</th>
                  <th>Profit in band</th>
                  <th>Tax</th>
                </tr>
              </thead>
              <tbody>
                {(tax?.bands || []).map((band) => (
                  <tr key={band.label}>
                    <td>{band.label}</td>
                    <td>{money(band.income)}</td>
                    <td>{money(band.tax)}</td>
                  </tr>
                ))}
                {tax?.bands?.length ? null : (
                  <tr>
                    <td colSpan={3}>No tax while taxable profit is zero or a loss.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </article>
        <article className="card">
          <h2>GST</h2>
          <p className="hint">Collected on income, claimed only on the business-use share of expenses.</p>
          <div className="table-wrap">
            <table>
              <tbody>
                <tr>
                  <td>GST collected</td>
                  <td>{money(data?.gst.output_gst)}</td>
                </tr>
                <tr>
                  <td>GST claimed</td>
                  <td>{money(data?.gst.input_gst)}</td>
                </tr>
                <tr>
                  <td>GST to pay</td>
                  <td>{money(data?.gst.gst_to_pay)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
      </div>
    </AppShell>
  );
}

function CategoryCard({ title, lines, empty }: { title: string; lines: Line[]; empty: string }) {
  const max = Math.max(...lines.map((line) => Math.abs(Number(line.net_amount) || 0)), 1);
  return (
    <article className="card">
      <h2>{title}</h2>
      {lines.length === 0 ? <p className="hint">{empty}</p> : null}
      {lines.map((line) => (
        <div key={line.account_name} style={{ marginBottom: 10 }}>
          <p className="hint">
            {line.account_name} · {money(line.net_amount)}
          </p>
          <div className="bar">
            <span style={{ width: `${(Math.abs(Number(line.net_amount) || 0) / max) * 100}%` }} />
          </div>
        </div>
      ))}
    </article>
  );
}
