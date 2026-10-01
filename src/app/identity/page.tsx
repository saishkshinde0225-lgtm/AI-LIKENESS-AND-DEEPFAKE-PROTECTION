import { Fingerprint } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";

export default function IdentityPage() {
  return (
    <>
      <PageHeader
        title="Identity Protection"
        description="Manage protected identities and consent policies."
      />
      <EmptyState
        icon={Fingerprint}
        title="No protected identities yet"
        description="Protected identities and their consent policies will appear here."
      />
    </>
  );
}