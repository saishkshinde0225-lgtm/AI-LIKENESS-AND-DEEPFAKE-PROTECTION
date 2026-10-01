"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { navigationItems } from "@/config/navigation";

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav className="sidebar-navigation" aria-label="Primary navigation">
      <p className="sidebar-section-label">Workspace</p>
      <ul className="navigation-list">
        {navigationItems.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href;

          return (
            <li key={href}>
              <Link
                className="navigation-link"
                href={href}
                aria-current={isActive ? "page" : undefined}
                onClick={(event) => {
                  event.currentTarget.closest("details")?.removeAttribute("open");
                }}
              >
                <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}