import { useEffect, useState } from 'react';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useOperators } from '@/hooks/useOperators';
import type { ToolMeta } from '@/hooks/useTools';
import type { ToolStat } from '@/hooks/useToolStats';

type Props = {
  tool: (ToolMeta & Partial<ToolStat>) | null;
  onOpenChange: (open: boolean) => void;
};

type UserPermission = { user_id: string; enabled: boolean };

/**
 * Lazy: only when the sheet is open AND we have an operator list,
 * fan out a permissions GET per user and surface those whose explicit
 * row for this tool differs from the implicit default (enabled: true).
 */
function usePerUserOverrides(toolName: string | null) {
  const { data: operators } = useOperators();
  return useQuery({
    enabled: !!toolName && !!operators?.length,
    queryKey: ['toolOverrides', toolName],
    queryFn: async (): Promise<UserPermission[]> => {
      if (!toolName || !operators) return [];
      const results = await Promise.all(
        operators.map(async (op) => {
          const res = await api.get<{ permissions: { tool_name: string; enabled: boolean }[] }>(
            `/admin/api/permissions/${encodeURIComponent(op.user_id)}`,
          );
          const row = res.permissions.find((p) => p.tool_name === toolName);
          return { user_id: op.user_id, enabled: row?.enabled ?? true };
        }),
      );
      return results.filter((r) => r.enabled === false); // only explicit disables
    },
  });
}

export function ToolDetailSheet({ tool, onOpenChange }: Props) {
  // Cache the last non-null tool so the sheet content doesn't blank out during the close animation.
  const [staged, setStaged] = useState(tool);
  useEffect(() => { if (tool) setStaged(tool); }, [tool]);
  const display = tool ?? staged;

  const overrides = usePerUserOverrides(tool?.name ?? null);

  return (
    <Sheet open={!!tool} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="font-mono text-sm">{display?.name}</SheetTitle>
          <SheetDescription>{display?.description || 'No description.'}</SheetDescription>
        </SheetHeader>

        {display && (
          <div className="space-y-6 mt-6">
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Activity
              </h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">Calls</dt>
                <dd>{display.call_count ?? 0}</dd>
                <dt className="text-muted-foreground">Error rate</dt>
                <dd>{display.error_rate ?? '0.0%'}</dd>
                <dt className="text-muted-foreground">Avg latency</dt>
                <dd>{display.avg_duration_ms != null ? `${display.avg_duration_ms} ms` : '—'}</dd>
                <dt className="text-muted-foreground">Last called</dt>
                <dd>{display.last_called ?? '—'}</dd>
              </dl>
            </section>

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Per-user overrides
              </h3>
              {overrides.isLoading ? (
                <Skeleton className="h-12 w-full" />
              ) : overrides.data?.length ? (
                <div className="space-y-1">
                  {overrides.data.map((u) => (
                    <div key={u.user_id} className="flex justify-between items-center text-sm">
                      <span className="font-mono text-xs">{u.user_id}</span>
                      <Badge variant="destructive">disabled</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No per-user overrides — this tool follows the global toggle.
                </p>
              )}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
