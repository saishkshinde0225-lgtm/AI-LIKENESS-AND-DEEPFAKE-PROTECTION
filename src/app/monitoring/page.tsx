import { Activity } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

export default function MonitoringPage() {
  return (
    <>
      <PageHeader
        title="Monitoring"
        description="Review monitored sources and recent activity."
      />
      <EmptyState
        icon={Activity}
        title="No sources monitored"
        description="Monitored sources and their recent activity will appear here."
      />
    </>
  );
}