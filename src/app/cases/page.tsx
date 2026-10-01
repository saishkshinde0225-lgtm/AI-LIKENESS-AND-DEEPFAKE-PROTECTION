import { BriefcaseBusiness } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

export default function CasesPage() {
  return (
    <>
      <PageHeader
        title="Cases"
        description="Review detection incidents and takedown cases."
      />
      <EmptyState
        icon={BriefcaseBusiness}
        title="No cases to review"
        description="Detection incidents and takedown requests will appear here."
      />
    </>
  );
}