import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';

export function TopBar({ title }: { title: string }) {
  const qc = useQueryClient();
  return (
    <header className="h-14 px-6 border-b border-border bg-primary text-primary-foreground flex items-center justify-between">
      <h1 className="font-serif font-bold text-base tracking-wider uppercase">{title}</h1>
      <Button
        size="sm"
        variant="secondary"
        onClick={() => qc.invalidateQueries()}
        className="gap-2"
      >
        <RefreshCw className="w-3 h-3" /> Refresh
      </Button>
    </header>
  );
}
