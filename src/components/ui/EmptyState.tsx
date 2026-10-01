import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
}: EmptyStateProps) {
  return (
    <section className="empty-state" aria-labelledby="empty-state-title">
      <span className="empty-state__icon">
        <Icon size={20} strokeWidth={1.8} aria-hidden="true" />
      </span>
      <h2 id="empty-state-title" className="empty-state__title">
        {title}
      </h2>
      <p className="empty-state__description">{description}</p>
    </section>
  );
}