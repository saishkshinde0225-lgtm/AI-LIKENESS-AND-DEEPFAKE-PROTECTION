import { Settings } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="Manage account and application preferences."
      />
      <EmptyState
        icon={Settings}
        title="No preferences configured"
        description="Account and application preferences will appear here."
      />
    </>
  );
}