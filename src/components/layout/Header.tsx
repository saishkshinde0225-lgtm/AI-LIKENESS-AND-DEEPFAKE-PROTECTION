"use client";

import { Bell, ChevronDown } from "lucide-react";
import { usePathname } from "next/navigation";
import { navigationItems } from "@/config/navigation";
import { currentUser } from "@/mocks/user";

export function Header() {
  const pathname = usePathname();
  const currentPage = navigationItems.find(({ href }) => href === pathname);

  return (
    <header className="top-header">
      <div className="header-context" aria-label="Current page">
        <span className="header-context__root">Workspace</span>
        <span className="header-context__current">
          {currentPage?.label ?? "Overview"}
        </span>
      </div>
      <div className="header-actions">
        <button
          className="icon-button"
          type="button"
          aria-label="Notifications, one item to review"
        >
          <Bell size={17} strokeWidth={1.8} aria-hidden="true" />
          <span className="notification-indicator" aria-hidden="true" />
        </button>
        <details className="profile-menu">
          <summary aria-label={`Open profile menu for ${currentUser.name}`}>
            <span className="user-avatar" aria-hidden="true">
              {currentUser.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="profile-menu__summary-copy">
              <span className="profile-menu__name">{currentUser.name}</span>
              <span className="profile-menu__role">{currentUser.role}</span>
            </span>
            <ChevronDown
              className="profile-menu__summary-chevron"
              size={14}
              aria-hidden="true"
            />
          </summary>
          <div className="profile-menu__panel">
            <p className="profile-menu__panel-name">{currentUser.name}</p>
            <p className="profile-menu__panel-role">{currentUser.role}</p>
          </div>
        </details>
      </div>
    </header>
  );
}