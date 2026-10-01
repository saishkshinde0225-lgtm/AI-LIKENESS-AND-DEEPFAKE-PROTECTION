import type { ReactNode } from "react";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="app-shell">
        <Sidebar />
        <div className="workspace">
          <Header />
          <main id="main-content" className="main-content">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}