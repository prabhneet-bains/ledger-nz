import { auth0AccessToken, auth0Configured } from "./auth0";
import { supabaseBrowser, supabaseConfigured } from "./supabase";

const API = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");
export const DEV_TOKEN_KEY = "ledger_dev_token";

export function devAuthEnabled(): boolean {
  return process.env.NEXT_PUBLIC_DEV_AUTH === "true";
}

function tokenExpired(token: string): boolean {
  try {
    const segment = token.split(".")[1];
    if (!segment) return true;
    const padded = segment.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(padded));
    if (!payload.exp) return false;
    return payload.exp * 1000 < Date.now() + 60_000;
  } catch {
    return true;
  }
}

async function errorMessage(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : JSON.stringify(item)))
        .join("; ");
    }
  } catch {
    /* plain text */
  }
  return text || res.statusText;
}

async function freshDevToken(): Promise<string> {
  const res = await fetch(`${API}/auth/dev-login`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
  const body = (await res.json()) as { access_token: string };
  window.localStorage.setItem(DEV_TOKEN_KEY, body.access_token);
  return body.access_token;
}

async function authHeader(refreshAuth0 = false): Promise<HeadersInit> {
  if (typeof window !== "undefined" && devAuthEnabled()) {
    let dev = window.localStorage.getItem(DEV_TOKEN_KEY);
    if (dev && tokenExpired(dev)) dev = await freshDevToken();
    if (dev) return { Authorization: `Bearer ${dev}` };
  }
  if (auth0Configured()) {
    const { access, idToken } = await auth0AccessToken(refreshAuth0);
    const headers: Record<string, string> = { Authorization: `Bearer ${access}` };
    if (idToken) headers["X-Auth0-Id-Token"] = idToken;
    return headers;
  }
  if (!supabaseConfigured()) throw new Error("Not signed in");
  const { data } = await supabaseBrowser().auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Not signed in");
  return { Authorization: `Bearer ${token}` };
}

async function send(path: string, init: RequestInit, retried = false): Promise<Response> {
  const headers = { ...(await authHeader(retried && auth0Configured())), ...(init.headers || {}) };
  const res = await fetch(`${API}${path}`, { ...init, headers });
  if (res.status === 401 && !retried && typeof window !== "undefined") {
    if (devAuthEnabled() && window.localStorage.getItem(DEV_TOKEN_KEY)) {
      await freshDevToken();
      return send(path, init, true);
    }
    if (auth0Configured()) return send(path, init, true);
  }
  return res;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await send(path, {});
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function apiSend<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await send(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function apiUpload<T>(path: string, file: File, fields?: Record<string, string>): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  if (fields) {
    for (const [key, value] of Object.entries(fields)) form.append(key, value);
  }
  const res = await send(path, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export function money(value: string | number | null | undefined): string {
  const n = Number(value || 0);
  return n.toLocaleString("en-NZ", { style: "currency", currency: "NZD" });
}
