"use client";

import { FormEvent, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import { usePeriod } from "@/components/PeriodFilter";
import { apiGet, apiUpload, money } from "@/lib/api";
import { withPeriod } from "@/lib/period";

type Receipt = {
  receipt_id: string;
  vendor_name: string;
  extracted_amount: string;
  confidence_score: number;
  inferred_category: string;
  drive_file_url: string | null;
  ocr_raw: string;
  created_at: string;
};

type Setup = {
  ocr_provider: string;
  drive_ready: boolean;
  drive_message: string;
  steps: string[];
};

export default function ReceiptsPage() {
  const period = usePeriod();
  const [rows, setRows] = useState<Receipt[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [setup, setSetup] = useState<Setup | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!period.start || !period.end || period.start > period.end) return;
    const [receipts, status] = await Promise.all([
      apiGet<Receipt[]>(withPeriod("/receipts", period)),
      apiGet<Setup>("/receipts/setup"),
    ]);
    setRows(receipts);
    setSetup(status);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period.start, period.end]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiUpload<{ needs_review: boolean; ocr_error: string | null; drive_message: string; ocr_provider: string }>(
        "/receipts/upload",
        file,
        { txn_date: date },
      );
      const review = result.needs_review ? "Queued for review." : "Auto-coded.";
      const ocr = result.ocr_error ? `OCR: ${result.ocr_error}` : `OCR via ${result.ocr_provider}.`;
      setMessage(`${review} ${ocr} ${result.drive_message}`);
      setFile(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <h1>Receipts</h1>
      <p className="hint">
        Each upload is recorded in the ledger. When Google Drive is connected, the file is stored under{" "}
        <code>/FY&#123;year ending 31 March&#125;/Expenses/&#123;Category&#125;/&#123;Vendor&#125;_&#123;Date&#125;</code>.
      </p>
      {setup ? (
        <article className="card" style={{ marginTop: 16 }}>
          <p>
            OCR: <strong>{setup.ocr_provider === "off" ? "not configured" : setup.ocr_provider}</strong>. Drive:{" "}
            <strong>{setup.drive_ready ? "ready" : "not connected"}</strong>. {setup.drive_message}
          </p>
          {setup.drive_ready ? null : (
            <ol>
              {setup.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}
        </article>
      ) : null}
      <form className="card row" onSubmit={onSubmit} style={{ marginTop: 16 }}>
        <label>
          Date
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Scan or PDF
          <input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        <button className="btn" disabled={!file || busy}>
          {busy ? "Processing…" : "Upload"}
        </button>
      </form>
      {message ? <p className="hint">{message}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <article className="card table-wrap" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr>
              <th>Vendor</th>
              <th>Amount</th>
              <th>Category</th>
              <th>Confidence</th>
              <th>OCR JSON</th>
              <th>Drive</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.receipt_id}>
                <td>{row.vendor_name}</td>
                <td>{money(row.extracted_amount)}</td>
                <td>{row.inferred_category}</td>
                <td>{Math.round((row.confidence_score || 0) * 100)}%</td>
                <td>{row.ocr_raw ? "Saved" : "—"}</td>
                <td>
                  {row.drive_file_url ? (
                    <a href={row.drive_file_url} target="_blank" rel="noreferrer">
                      Open
                    </a>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </AppShell>
  );
}
