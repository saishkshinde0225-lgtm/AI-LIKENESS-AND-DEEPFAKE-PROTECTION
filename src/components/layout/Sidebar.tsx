import Link from "next/link";
import { Menu, Shield } from "lucide-react";
import { SidebarNav } from "@/components/navigation/SidebarNav";
import { ProtectionStatus } from "@/components/status/ProtectionStatus";
import { currentUser } from "@/mocks/user";

function BrandLockup({ compact = false }: { compact?: boolean }) {
  return (
    <Link className="brand-lockup" href="/dashboard" aria-label="AI Likeness Protection overview">
      <span className="brand-mark">
        <Shield size={19} strokeWidth={1.8} aria-hidden="true" />
      </span>
      {!compact && <span className="brand-name">AI Likeness Protection</span>}
    </Link>
  );
}

function UserProfile() {
  return (
    <div className="user-profile">
      <span className="user-avatar" aria-hidden="true">
        {currentUser.name.slice(0, 1).toUpperCase()}
      </span>
      <span className="user-profile__copy">
        <span className="user-profile__name">{currentUser.name}</span>
        <span className="user-profile__role">{currentUser.role}</span>
      </span>
    </div>
  );
}

export function Sidebar() {
  return (
    <>
      <aside className="sidebar" aria-label="Application sidebar">
        <BrandLockup />
        <SidebarNav />
        <div className="sidebar-footer">
          <ProtectionStatus />
          <UserProfile />
        </div>
      </aside>
      <div className="mobile-navigation">
        <BrandLockup compact />
        <details className="mobile-navigation__menu">
          <summary>
            <Menu size={17} aria-hidden="true" />
            <span>Menu</span>
          </summary>
          <div className="mobile-navigation__panel">
            <div className="mobile-navigation__status">
              <ProtectionStatus compact />
            </div>
            <SidebarNav />
          </div>
        </details>
      </div>
    </>
  );
}