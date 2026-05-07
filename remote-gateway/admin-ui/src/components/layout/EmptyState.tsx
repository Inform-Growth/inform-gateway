import type { LucideIcon } from 'lucide-react';

export function EmptyState({
  icon: Icon, title, body, action,
}: { icon: LucideIcon; title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <Icon className="w-12 h-12 text-muted-foreground mb-4" />
      <h3 className="font-serif text-lg font-bold mb-1">{title}</h3>
      <p className="text-sm text-muted-foreground max-w-sm mb-4">{body}</p>
      {action}
    </div>
  );
}
