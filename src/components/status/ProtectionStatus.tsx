import { ShieldCheck } from "lucide-react";

interface ProtectionStatusProps {
  compact?: boolean;
}

export function ProtectionStatus({ compact = false }: ProtectionStatusProps) {
  return (
    <div
      className={`protection-status${compact ? " protection-status--compact" : ""}`}
      role="status"
      aria-label="Protection status: Protection Active"
    >
      <ShieldCheck
        className="protection-status__icon"
        size={18}
        aria-hidden="true"
      />
      <span className="protection-status__copy">
        <span className="protection-status__label">Protection status</span>
        <span className="protection-status__value">Protection Active</span>
      </span>
    </div>
  );
}