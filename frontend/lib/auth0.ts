import { Auth0Client, createAuth0Client } from "@auth0/auth0-spa-js";

let clientPromise: Promise<Auth0Client> | null = null;
let redirectPromise: Promise<string | null> | null = null;

function domain(): string {
  return (process.env.NEXT_PUBLIC_AUTH0_DOMAIN || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
}

export function auth0Configured(): boolean {
  return Boolean(domain() && process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID && process.env.NEXT_PUBLIC_AUTH0_AUDIENCE);
}

export function auth0Browser(): Promise<Auth0Client> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Auth0 runs in the browser"));
  }
  if (!clientPromise) {
    clientPromise = createAuth0Client({
      domain: domain(),
      clientId: process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID || "",
      authorizationParams: {
        redirect_uri: `${window.location.origin}/`,
        audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE,
        scope: "openid profile email",
      },
      cacheLocation: "memory",
      useRefreshTokens: true,
      workerUrl: `${window.location.origin}/auth0-spa-js.worker.production.js`,
    });
  }
  return clientPromise;
}

function safeReturnTo(value: unknown): string {
  if (typeof value === "string" && value.startsWith("/app/") && !value.startsWith("//")) {
    return value;
  }
  return "/app/";
}

async function runRedirect(): Promise<string | null> {
  const params = new URLSearchParams(window.location.search);
  if (params.get("error")) {
    const message = params.get("error_description") || "Sign-in was cancelled";
    window.history.replaceState({}, document.title, window.location.pathname);
    throw new Error(message.replace(/\+/g, " "));
  }
  const client = await auth0Browser();
  if (params.has("code") && params.has("state")) {
    const result = await client.handleRedirectCallback();
    window.history.replaceState({}, document.title, window.location.pathname);
    const appState = result?.appState as { returnTo?: unknown } | undefined;
    return safeReturnTo(appState?.returnTo);
  }
  if (await client.isAuthenticated()) return "/app/";
  return null;
}

export function finishAuth0Redirect(): Promise<string | null> {
  if (!redirectPromise) redirectPromise = runRedirect();
  return redirectPromise;
}

function audienceParams(extra: Record<string, string> = {}) {
  return {
    audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE,
    scope: "openid profile email",
    ...extra,
  };
}

export async function startAuth0Login(mode: "signin" | "signup"): Promise<void> {
  const client = await auth0Browser();
  await client.loginWithRedirect({
    appState: { returnTo: "/app/" },
    authorizationParams: audienceParams(mode === "signup" ? { screen_hint: "signup" } : {}),
  });
}

export async function auth0Logout(): Promise<void> {
  const client = await auth0Browser();
  await client.logout({ logoutParams: { returnTo: `${window.location.origin}/` } });
}

export async function auth0AccessToken(force = false): Promise<{ access: string; idToken?: string }> {
  const client = await auth0Browser();
  // Audience must be repeated here. A refresh from an older login without the API
  // audience can otherwise return an opaque token the ledger API rejects.
  const access = await client.getTokenSilently({
    authorizationParams: audienceParams(),
    ...(force ? { cacheMode: "off" as const } : {}),
  });
  if (!access) throw new Error("Not signed in");
  if (access.split(".").length !== 3) {
    throw new Error("Sign out and sign in again so Auth0 can issue an API access token");
  }
  const id = await client.getIdTokenClaims();
  return { access, idToken: id?.__raw };
}

export async function auth0SignedIn(): Promise<boolean> {
  const client = await auth0Browser();
  if (await client.isAuthenticated()) return true;
  try {
    const access = await client.getTokenSilently({
      authorizationParams: audienceParams(),
      timeoutInSeconds: 8,
    });
    return Boolean(access);
  } catch {
    return false;
  }
}
