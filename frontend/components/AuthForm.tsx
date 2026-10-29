"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { auth0Configured, finishAuth0Redirect, startAuth0Login } from "@/lib/auth0";
import { DEV_TOKEN_KEY, devAuthEnabled } from "@/lib/api";
import { supabaseBrowser, supabaseConfigured } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function AuthForm({ mode }: { mode: "signin" | "signup" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const showAuth0 = auth0Configured();
  const showSupabase = supabaseConfigured() && !showAuth0;
  const showDev = devAuthEnabled();
  const [checking, setChecking] = useState(showAuth0);

  useEffect(() => {
    if (!showAuth0) return;
    let cancelled = false;
    finishAuth0Redirect()
      .then((dest) => {
        if (cancelled) return;
        if (dest) {
          router.replace(dest);
          return;
        }
        setChecking(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Sign-in failed");
        setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [router, showAuth0]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    if (!showSupabase) {
      setBusy(false);
      return;
    }
    try {
      const supabase = supabaseBrowser();
      if (mode === "signup") {
        const { error: err } = await supabase.auth.signUp({
          email,
          password,
          options: { data: { full_name: name } },
        });
        if (err) throw err;
        window.location.href = "/app/";
      } else {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password });
        if (err) throw err;
        window.location.href = "/app/";
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setBusy(false);
    }
  }

  async function auth0Login() {
    setBusy(true);
    setError("");
    try {
      await startAuth0Login(mode);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setBusy(false);
    }
  }

  async function devLogin() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch(`${API}/auth/dev-login`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const body = await res.json();
      window.localStorage.setItem(DEV_TOKEN_KEY, body.access_token);
      window.location.href = "/app/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Local sign-in failed");
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={onSubmit}>
        <p className="serif" style={{ margin: 0, color: "var(--brass)" }}>
          Ledger NZ
        </p>
        <h1 style={{ marginTop: 6 }}>{mode === "signup" ? "Open the books" : "Sign in"}</h1>
        <p className="hint">Practice ledger for GST, CSV bank imports, receipts, and the vehicle logbook.</p>
        {checking ? <p className="hint">Checking your sign-in…</p> : null}
        {showAuth0 && !checking ? (
          <button className="btn" type="button" onClick={auth0Login} disabled={busy} style={{ width: "100%", marginTop: 12 }}>
            {busy ? "Please wait…" : mode === "signup" ? "Create account" : "Sign in"}
          </button>
        ) : null}
        {showDev ? (
          <button className="btn" type="button" onClick={devLogin} disabled={busy} style={{ width: "100%", marginTop: 12 }}>
            {busy ? "Please wait…" : "Continue with the local practice"}
          </button>
        ) : null}
        {showSupabase ? (
          <>
            {mode === "signup" ? (
              <label style={{ marginTop: 12 }}>
                Practice / your name
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </label>
            ) : null}
            <div className="grid" style={{ gap: 12, marginTop: 12 }}>
              <label>
                Email
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required={showSupabase} />
              </label>
              <label>
                Password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
              </label>
              <button className="btn secondary" type="submit" disabled={busy}>
                {busy ? "Please wait…" : mode === "signup" ? "Create account" : "Sign in with email"}
              </button>
            </div>
          </>
        ) : null}
        {error ? <p className="error">{error}</p> : null}
        {showAuth0 && !checking ? (
          <p className="hint" style={{ marginTop: 16 }}>
            Sign-in is handled by Auth0. Passwords stay there, and this ledger only receives a verified login.
          </p>
        ) : null}
        {!showDev && !showSupabase && !showAuth0 ? (
          <p className="hint">Set Auth0 or Supabase keys, or NEXT_PUBLIC_DEV_AUTH=true for a local ledger.</p>
        ) : null}
        {showSupabase || showAuth0 ? (
          <p className="hint" style={{ marginTop: 16 }}>
            {mode === "signup" ? (
              <>
                Already provisioned? <Link href="/">Sign in</Link>
              </>
            ) : (
              <>
                Need a practice? <Link href="/signup/">Create one</Link>
              </>
            )}
          </p>
        ) : null}
      </form>
    </div>
  );
}
