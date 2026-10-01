import { Activity } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { dashboardMetrics, recentActivity } from "@/mocks/dashboard";

export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Monitor the protection status of your identity and reported incidents."
      />

      <section aria-label="Protection overview">
        <dl className="metric-grid">
          {dashboardMetrics.map((metric) => (
            <div className="metric-card" key={metric.id}>
              <dt className="metric-card__label">{metric.label}</dt>
              <dd className="metric-card__content">
                {metric.kind === "status" ? (
                  <StatusBadge tone={metric.tone}>{metric.value}</StatusBadge>
                ) : (
                  <span
                    className={`metric-card__value metric-card__value--${metric.tone}`}
                  >
                    {metric.value}
                  </span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="activity-panel" aria-labelledby="recent-activity-title">
        <div className="activity-panel__header">
          <div>
            <h2 id="recent-activity-title">Recent Activity</h2>
            <p>Latest identity protection events</p>
          </div>
          <Activity size={18} strokeWidth={1.8} aria-hidden="true" />
        </div>
        <ol className="activity-list">
          {recentActivity.map((item) => (
            <li className="activity-row" key={item.id}>
              <div className="activity-row__main">
                <p className="activity-row__title">{item.title}</p>
                <p className="activity-row__detail">{item.detail}</p>
              </div>
              <div className="activity-row__meta">
                <StatusBadge tone={item.tone}>{item.statusLabel}</StatusBadge>
                <time className="activity-row__time">{item.time}</time>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}