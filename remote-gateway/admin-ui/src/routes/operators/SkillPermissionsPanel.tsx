import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/skeleton';
import { useSkillPermissions, useSetSkillPermission } from '@/hooks/useSkillPermissions';
import { toast } from 'sonner';

export function SkillPermissionsPanel({ userId }: { userId: string | null }) {
  const [filter, setFilter] = useState('');
  const { data, isLoading } = useSkillPermissions(userId);
  const setPerm = useSetSkillPermission(userId ?? '');

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = filter.toLowerCase();
    return q ? list.filter((p) => p.skill_name.toLowerCase().includes(q)) : list;
  }, [data, filter]);

  if (!userId) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          Select an operator to manage their skill permissions.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Skill permissions — {userId}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Input
          placeholder="Filter skills…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : filtered.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            {filter ? 'No skills match the filter.' : 'No skills available.'}
          </div>
        ) : (
          <div className="divide-y divide-border max-h-[60vh] overflow-y-auto">
            {filtered.map((p) => (
              <div key={p.skill_name} className="flex items-center justify-between py-2">
                <span className="font-mono text-xs">{p.skill_name}</span>
                <Switch
                  checked={p.enabled}
                  onCheckedChange={(enabled) => {
                    setPerm.mutate(
                      { skill_name: p.skill_name, enabled },
                      {
                        onError: (err) =>
                          toast.error(
                            err instanceof Error ? err.message : 'Failed to update skill permission',
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
