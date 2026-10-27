import { copyFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function origin(value) {
  if (!value) return "";
  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}

const connect = new Set(["'self'", "https://*.auth0.com", "https://*.supabase.co"]);
const auth0Host = (process.env.NEXT_PUBLIC_AUTH0_DOMAIN || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
if (auth0Host) connect.add(`https://${auth0Host}`);
const supabaseOrigin = origin(process.env.NEXT_PUBLIC_SUPABASE_URL);
if (supabaseOrigin) connect.add(supabaseOrigin);
const apiOrigin = origin(process.env.NEXT_PUBLIC_API_URL);
if (apiOrigin) connect.add(apiOrigin);
if (!apiOrigin || apiOrigin.startsWith("http://localhost") || apiOrigin.startsWith("http://127.0.0.1")) {
  connect.add("http://localhost:8000");
  connect.add("http://127.0.0.1:8000");
}

const frame = new Set(["https://*.auth0.com"]);
if (auth0Host) frame.add(`https://${auth0Host}`);

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data:",
  `connect-src ${[...connect].join(" ")}`,
  `frame-src ${[...frame].join(" ")}`,
  "worker-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
].join("; ");

const file = `/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Strict-Transport-Security: max-age=31536000
  Content-Security-Policy: ${csp}
`;

const publicDir = join(dirname(fileURLToPath(import.meta.url)), "..", "public");
writeFileSync(join(publicDir, "_headers"), file);
copyFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "node_modules", "@auth0", "auth0-spa-js", "dist", "auth0-spa-js.worker.production.js"),
  join(publicDir, "auth0-spa-js.worker.production.js"),
);
