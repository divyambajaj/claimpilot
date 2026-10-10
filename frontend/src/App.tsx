import { useEffect, useState } from "react";
import { api } from "./api/client";
import type { Health } from "./types";
import { ChatPage } from "./pages/ChatPage";
import { AdminPage } from "./pages/AdminPage";

const routeOf = () => (window.location.hash.startsWith("#/admin") ? "admin" : "chat");

export function App() {
  const [route, setRoute] = useState(routeOf);
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    const on = () => setRoute(routeOf());
    window.addEventListener("hashchange", on);
    api.health().then(setHealth).catch(() => setHealth(null));
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const nav = (href: string, label: string, active: boolean) => (
    <a
      href={href}
      aria-current={active ? "page" : undefined}
      className={`relative flex h-14 items-center px-1 text-sm transition-colors ${active ? "text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-px after:bg-ink" : "text-ink-3 hover:text-ink"}`}
    >
      {label}
    </a>
  );

  return (
    <div className="flex h-[100dvh] flex-col">
      <header className="flex h-14 shrink-0 items-center gap-6 border-b border-line bg-surface px-4 sm:px-6">
        <a href="#/" aria-label="ClaimPilot home" className="text-[15px] font-semibold tracking-[-0.02em] text-ink">
          Claim<span className="text-accent">Pilot</span>
        </a>
        <nav className="flex items-center gap-5" aria-label="Primary">
          {nav("#/", "Chat", route === "chat")}
          {nav("#/admin", "Admin", route === "admin")}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {health?.replay_mode && (
            <span
              className="inline-flex h-6 items-center gap-1.5 rounded border border-line px-2 text-2xs text-ink-2"
              title="Model responses are replayed from recorded runs. Use the sample receipts."
            >
              <span className="h-1.5 w-1.5 rounded-full bg-ochre" aria-hidden />
              Demo mode
            </span>
          )}
          <span className="hidden text-xs text-ink-3 sm:inline">demo-user</span>
        </div>
      </header>
      <main className="flex min-h-0 flex-1 flex-col">
        {/* Chat stays mounted so a claim in progress survives a visit to Admin. */}
        <div className={route === "chat" ? "contents" : "hidden"}>
          <ChatPage />
        </div>
        {route === "admin" && <AdminPage />}
      </main>
    </div>
  );
}
