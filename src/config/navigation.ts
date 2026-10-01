import {
  Activity,
  BriefcaseBusiness,
  Fingerprint,
  LayoutDashboard,
  ScanSearch,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavigationItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const navigationItems: NavigationItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/identity", label: "Identity Protection", icon: Fingerprint },
  { href: "/detect", label: "Analyze Content", icon: ScanSearch },
  { href: "/cases", label: "Cases", icon: BriefcaseBusiness },
  { href: "/monitoring", label: "Monitoring", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
];