import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import { usePermissions, useSetPermission } from '@/hooks/usePermissions';
import { toast } from 'sonner';

export function PermissionsPanel({ userId }: { userId: string | null }) {
  const [filter, setFilter] = useState('');
  const { data, isLoading } = usePermissions(userId);
  const setPerm = useSetPermission(userId ?? '');

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = filter.toLowerCase();
    return q ? list.filter((p) => p.tool_name.toLowerCase().includes(q)) : list;
  }, [data, filter]);

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
            {filtered.map((p) => (
              <div key={p.tool_name} className="flex items-center justify-between py-2">
                <span className="font-mono text-xs">{p.tool_name}</span>
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
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
