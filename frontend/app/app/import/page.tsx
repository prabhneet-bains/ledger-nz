"use client";

import { FormEvent, useState } from "react";
import AppShell from "@/components/AppShell";
import { apiUpload, money } from "@/lib/api";

type Mapping = {
  date: string;
  amount: string;
  debit: string;
  credit: string;
  payee: string;
  reference: string;
  description: string;
};

type Preview = {
  headers: string[];
  preset: string;
  suggested_mapping: Partial<Record<keyof Mapping, string | null>>;
  sample_rows: Record<string, string>[];
  row_count: number;
};

type AnalyzedRow = {
  line: number;
  date: string;
  payee: string;
  gross_amount: string;
  account_name: string | null;
  is_internal_transfer: boolean;
  is_duplicate: boolean;
  status: string;
  reason: string;
};

type AnalyzeResponse = {
  row_count: number;
  ready: number;
  pending_review: number;
  internal_transfers: number;
  duplicates: number;
  errors: { line: number; error: string }[];
  rows: AnalyzedRow[];
};

const EMPTY: Mapping = { date: "", amount: "", debit: "", credit: "", payee: "", reference: "", description: "" };

const FIELDS: { key: keyof Mapping; label: string }[] = [
  { key: "date", label: "Date" },
  { key: "amount", label: "Amount (signed)" },
  { key: "debit", label: "Debit (optional)" },
  { key: "credit", label: "Credit (optional)" },
  { key: "payee", label: "Payee" },
  { key: "reference", label: "Reference" },
  { key: "description", label: "Details" },
];

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Mapping>(EMPTY);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function onFile(next: File | null) {
    setFile(next);
    setPreview(null);
    setAnalysis(null);
    setResult("");
    setError("");
    if (!next) return;
    setBusy(true);
    try {
      const body = await apiUpload<Preview>("/csv/preview", next);
      setPreview(body);
      const suggested = body.suggested_mapping || {};
      setMapping({
        date: suggested.date || "",
        amount: suggested.amount || "",
        debit: suggested.debit || "",
        credit: suggested.credit || "",
        payee: suggested.payee || "",
        reference: suggested.reference || "",
        description: suggested.description || "",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read CSV");
    } finally {
      setBusy(false);
    }
  }

  async function onAnalyze(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setResult("");
    try {
      const body = await apiUpload<AnalyzeResponse>("/csv/analyze", file, { mapping: JSON.stringify(mapping) });
      setAnalysis(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setBusy(false);
    }
  }

  async function onImport() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = await apiUpload<{ inserted: number; skipped_duplicates: number }>("/csv/import", file, {
        mapping: JSON.stringify(mapping),
      });
      setResult(`Imported ${body.inserted} rows. Skipped ${body.skipped_duplicates} duplicates.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <div className="top">
        <div>
          <h1>Import a bank CSV</h1>
          <p className="hint">
            Map your bank’s columns, then import. Positive amounts are income. Negative amounts are expenses. Transfers are
            ignored in the P&amp;L. <a href="/sample-bank.csv">Download a sample</a>.
          </p>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {result ? <p className="hint">{result}</p> : null}
      <label
        className="drop"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          onFile(event.dataTransfer.files?.[0] || null);
        }}
      >
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => onFile(event.target.files?.[0] || null)}
        />
        <strong>{file ? file.name : "Drop a CSV here, or choose a file"}</strong>
        <span className="hint">{busy ? "Reading…" : "Day-first dates, such as 01/10/2026"}</span>
      </label>

      {preview ? (
        <form className="card" onSubmit={onAnalyze} style={{ marginTop: 16 }}>
          <h2>
            {preview.preset} · {preview.row_count} rows
          </h2>
          <div className="map-grid">
            {FIELDS.map((field) => (
              <label key={field.key}>
                {field.label}
                <select
                  value={mapping[field.key]}
                  onChange={(event) => setMapping({ ...mapping, [field.key]: event.target.value })}
                >
                  <option value="">—</option>
                  {preview.headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <button className="btn" type="submit" disabled={busy} style={{ marginTop: 12 }}>
            Analyse
          </button>
          {preview.sample_rows.length ? (
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
                <thead>
                  <tr>
                    {preview.headers.map((header) => (
                      <th key={header}>{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.slice(0, 3).map((row, index) => (
                    <tr key={index}>
                      {preview.headers.map((header) => (
                        <td key={header}>{row[header]}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </form>
      ) : null}

      {analysis ? (
        <article className="card" style={{ marginTop: 16 }}>
          <div className="row">
            <span className="badge ok">{analysis.ready} ready</span>
            <span className="badge pending">{analysis.pending_review} to review</span>
            <span className="badge ignored">{analysis.internal_transfers} transfers ignored</span>
            {analysis.duplicates ? <span className="badge pending">{analysis.duplicates} already in the ledger</span> : null}
            <button className="btn" type="button" onClick={onImport} disabled={busy}>
              Import into the ledger
            </button>
          </div>
          {analysis.errors.length ? (
            <p className="error">
              {analysis.errors.length} rows could not be read. First: line {analysis.errors[0].line} {analysis.errors[0].error}
            </p>
          ) : null}
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Payee</th>
                  <th>Amount</th>
                  <th>Account</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {analysis.rows.map((row) => (
                  <tr key={row.line}>
                    <td>{row.date}</td>
                    <td>{row.payee}</td>
                    <td>{money(row.gross_amount)}</td>
                    <td>{row.account_name || "—"}</td>
                    <td>
                      <span className={`badge ${row.status === "Reconciled" ? "ok" : row.status === "Ignored" ? "ignored" : "pending"}`}>
                        {row.is_duplicate ? "Already imported" : row.is_internal_transfer ? "Transfer" : row.status === "Pending_Review" ? "Review" : "Ready"}
                      </span>
                      <div className="hint">{row.reason}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}
    </AppShell>
  );
}
