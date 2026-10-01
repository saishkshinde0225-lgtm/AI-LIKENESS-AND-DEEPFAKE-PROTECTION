export interface User {
  id: string;
  name: string;
  role: string;
}

export interface ProtectedIdentity {
  id: string;
  displayName: string;
  identityType: "person" | "organization";
  status: "active" | "pending" | "paused";
}

export interface ConsentPolicy {
  id: string;
  identityId: string;
  scope: string;
  status: "active" | "pending" | "revoked";
  updatedAt: string;
}

export interface DetectionResult {
  id: string;
  source: string;
  confidence: number;
  status: "new" | "reviewing" | "confirmed" | "dismissed";
  detectedAt: string;
}

export interface TakedownCase {
  id: string;
  detectionId: string;
  platform: string;
  status: "pending" | "submitted" | "resolved";
  openedAt: string;
}

export interface DashboardMetric {
  id: string;
  label: string;
  value: string;
  kind: "status" | "count";
  tone: "active" | "alert" | "pending" | "neutral";
}

export interface ActivityItem {
  id: string;
  title: string;
  detail: string;
  time: string;
  tone: "active" | "alert" | "pending";
  statusLabel: string;
}