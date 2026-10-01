import type { ReactNode } from "react";

export type StatusTone = "active" | "pending" | "alert" | "neutral";

interface StatusBadgeProps {
  children: ReactNode;
  tone?: StatusTone;
}

export function StatusBadge({
  children,
  tone = "neutral",
}: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${tone}`}>
      <span className="status-badge__marker" aria-hidden="true" />
      {children}
    </span>
  );
}