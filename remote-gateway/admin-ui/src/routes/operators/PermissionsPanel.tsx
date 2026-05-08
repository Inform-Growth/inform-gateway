import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { usePermissions, useSetPermission } from '@/hooks/usePermissions';
import { useToolIntent, useSetToolIntent, useClearToolIntent } from '@/hooks/useToolIntent';
import { toast } from 'sonner';

export function PermissionsPanel({ userId }: { userId: string | null }) {
  const [filter, setFilter] = useState('');
  const { data, isLoading } = usePermissions(userId);
  const setPerm = useSetPermission(userId ?? '');

  const { data: intentData } = useToolIntent(userId);
  const setIntent = useSetToolIntent(userId ?? '');
  const clearIntent = useClearToolIntent(userId ?? '');

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = filter.toLowerCase();
    return q ? list.filter((p) => p.tool_name.toLowerCase().includes(q)) : list;
  }, [data, filter]);

  const intentByTool = useMemo(
    () => Object.fromEntries((intentData ?? []).map((r) => [r.tool_name, r])),
    [intentData],
  );

  if (!userId) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          Select an operator to manage their tool permissions.
        </CardContent>
      </Card>
    );
  }

  return (
    <TooltipProvider>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Permissions — {userId}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            placeholder="Filter tools…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : filtered.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              {filter ? 'No tools match the filter.' : 'No tools registered.'}
            </div>
          ) : (
            <div className="divide-y divide-border max-h-[60vh] overflow-y-auto">
              {/* Column headers */}
              <div className="flex items-center justify-between py-1 text-xs text-muted-foreground border-b">
                <span className="flex-1">Tool</span>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="w-12 text-center">Enabled</span>
                  <span className="w-12 text-center">Intent</span>
                  <span className="w-4" />
                </div>
              </div>
              {filtered.map((p) => {
                const intentRow = intentByTool[p.tool_name];
                return (
                  <div key={p.tool_name} className="flex items-center justify-between py-2 gap-3">
                    <span className="font-mono text-xs flex-1 truncate">{p.tool_name}</span>
                    <div className="flex items-center gap-3 shrink-0">
                      {/* Enabled switch */}
                      <div className="w-12 flex justify-center">
                        <Switch
                          checked={p.enabled}
                          onCheckedChange={(enabled) => {
                            setPerm.mutate(
                              { tool_name: p.tool_name, enabled },
                              {
                                onError: (err) =>
                                  toast.error(
                                    err instanceof Error ? err.message : 'Failed to update permission',
                                  ),
                              },
                            );
                          }}
                        />
                      </div>
                      {/* Requires intent switch */}
                      <div className="w-12 flex justify-center">
                        {intentRow?.locked ? (
                          <Tooltip>
                            <TooltipTrigger>
                              <span className="inline-flex">
                                <Switch disabled checked={false} />
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              Bootstrap tool — intent cannot be required.
                            </TooltipContent>
                          </Tooltip>
                        ) : (
                          <Switch
                            checked={intentRow?.requires_intent ?? false}
                            onCheckedChange={(requires_intent) => {
                              setIntent.mutate(
                                { tool_name: p.tool_name, requires_intent },
                                {
                                  onError: (err) =>
                                    toast.error(
                                      err instanceof Error
                                        ? err.message
                                        : 'Failed to update intent requirement',
                                    ),
                                },
                              );
                            }}
                          />
                        )}
                      </div>
                      {/* Reset button — visible when explicit and not locked */}
                      <div className="w-4 flex justify-center">
                        {intentRow?.explicit && !intentRow?.locked ? (
                          <button
                            type="button"
                            onClick={() => clearIntent.mutate(p.tool_name)}
                            className="text-xs text-muted-foreground hover:text-foreground"
                            title="Reset to default"
                          >
                            ↻
                          </button>
                        ) : (
                          <span />
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </TooltipProvider>
  );
}
