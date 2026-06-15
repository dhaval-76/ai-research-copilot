import { useEffect } from "react";
import { X, Info } from "lucide-react";

export interface Notification {
  id: number;
  message: string;
}

interface NotificationBannerProps {
  notification: Notification | null;
  onDismiss: () => void;
  autoDismissMs?: number;
}

export default function NotificationBanner({
  notification,
  onDismiss,
  autoDismissMs = 5000,
}: NotificationBannerProps) {
  useEffect(() => {
    if (!notification) return;
    const timer = window.setTimeout(onDismiss, autoDismissMs);
    return () => window.clearTimeout(timer);
  }, [notification, onDismiss, autoDismissMs]);

  if (!notification) return null;

  return (
    <div className="fixed top-4 right-4 z-50 max-w-sm">
      <div className="flex items-start gap-3 rounded-lg border border-accent/40 bg-surface shadow-lg px-4 py-3 text-sm">
        <Info size={16} className="text-accent shrink-0 mt-0.5" />
        <p className="text-text leading-snug pr-1">{notification.message}</p>
        <button
          onClick={onDismiss}
          aria-label="Dismiss notification"
          className="shrink-0 text-muted hover:text-text transition-colors"
        >
          <X size={15} />
        </button>
      </div>
    </div>
  );
}
