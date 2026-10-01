import { ScanSearch } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

export default function DetectPage() {
  return (
    <>
      <PageHeader
        title="Analyze Content"
        description="Analyze an image or video for potential unauthorized AI-generated likeness."
      />
      <EmptyState
        icon={ScanSearch}
        title="No content analyzed"
        description="Analysis results will appear here when content review is available."
      />
    </>
  );
}