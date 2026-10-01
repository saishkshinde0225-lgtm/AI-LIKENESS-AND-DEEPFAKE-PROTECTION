import type { ActivityItem, DashboardMetric } from "@/types/domain";

export const dashboardMetrics: DashboardMetric[] = [
  {
    id: "protection-status",
    label: "Protection Status",
    value: "Active",
    kind: "status",
    tone: "active",
  },
  {
    id: "detected-incidents",
    label: "Detected Incidents",
    value: "02",
    kind: "count",
    tone: "alert",
  },
  {
    id: "pending-cases",
    label: "Pending Cases",
    value: "01",
    kind: "count",
    tone: "pending",
  },
  {
    id: "resolved-cases",
    label: "Resolved Cases",
    value: "01",
    kind: "count",
    tone: "neutral",
  },
];

export const recentActivity: ActivityItem[] = [
  {
    id: "activity-match-01",
    title: "Potential likeness match detected",
    detail: "A monitored source requires review.",
    time: "12 min ago",
    tone: "alert",
    statusLabel: "Review required",
  },
  {
    id: "activity-case-01",
    title: "Takedown request submitted",
    detail: "The platform response is pending.",
    time: "Yesterday",
    tone: "pending",
    statusLabel: "Pending",
  },
  {
    id: "activity-monitoring-01",
    title: "Identity monitoring check completed",
    detail: "No new matches were reported.",
    time: "Yesterday",
    tone: "active",
    statusLabel: "Protected",
  },
];