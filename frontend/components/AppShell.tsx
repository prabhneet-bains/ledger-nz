"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { auth0Configured, auth0Logout, auth0SignedIn } from "@/lib/auth0";
import { DEV_TOKEN_KEY, devAuthEnabled } from "@/lib/api";
import { supabaseBrowser, supabaseConfigured } from "@/lib/supabase";
import PeriodFilter from "@/components/PeriodFilter";

const LINKS = [
  { href: "/app/", label: "Dashboard" },
  { href: "/app/import/", label: "Import CSV" },
  { href: "/app/transactions/", label: "Transactions" },
  { href: "/app/review/", label: "Review queue" },
  { href: "/app/receipts/", label: "Receipts" },
  { href: "/app/logbook/", label: "Logbook" },
  { href: "/app/accounts/", label: "Accounts" },
  { href: "/app/tax/", label: "Tax" },
  { href: "/app/assets/", label: "Assets" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (devAuthEnabled() && window.localStorage.getItem(DEV_TOKEN_KEY)) {
        if (!cancelled) setReady(true);
        return;
      }
      if (auth0Configured()) {
        const signedIn = await auth0SignedIn();
        if (cancelled) return;
        if (!signedIn) router.replace("/");
        else setReady(true);
        return;
      }
      if (!supabaseConfigured()) {
        router.replace("/");
        return;
      }
      const { data } = await supabaseBrowser().auth.getSession();
      if (cancelled) return;
      if (!data.session) router.replace("/");
      else setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function signOut() {
    window.localStorage.removeItem(DEV_TOKEN_KEY);
    if (auth0Configured()) {
      await auth0Logout();
      return;
    }
    if (supabaseConfigured()) await supabaseBrowser().auth.signOut();
    router.replace("/");
  }

  if (!ready) return <div className="main">Loading ledger…</div>;

  return (
    <div className="shell">
      <aside className="nav">
        <h1 className="brand serif">
          Ledger <span>NZ</span>
        </h1>
        <small>Consultancy practice books</small>
        {LINKS.map((link) => (
          <Link key={link.href} href={link.href} className={pathname === link.href ? "active" : ""}>
            {link.label}
          </Link>
        ))}
        <div className="spacer" />
        <button className="btn secondary" type="button" onClick={signOut}>
          Sign out
        </button>
      </aside>
      <div className="main">
        <PeriodFilter />
        {children}
      </div>
    </div>
  );
}
