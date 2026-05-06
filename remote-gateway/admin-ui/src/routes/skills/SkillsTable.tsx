import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { DataTable } from '@/components/data-table/DataTable';
import { useSkills, useDeleteSkill } from '@/hooks/useSkills';
import { isSystemSkill, type Skill } from '@/lib/skillSchema';

export function SkillsTable({ onEdit }: { onEdit: (s: Skill) => void }) {
  const { data, isLoading } = useSkills();
  const del = useDeleteSkill();

  const columns = useMemo<ColumnDef<Skill>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Name',
        cell: ({ row }) => (
          <span className="font-mono text-xs flex items-center gap-2">
            {row.original.name}
            {isSystemSkill(row.original) && (
              <Badge variant="secondary" className="gap-1">
                <ShieldCheck className="w-3 h-3" /> system
              </Badge>
            )}
          </span>
        ),
      },
      { accessorKey: 'description', header: 'Description' },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) => {
          const s = row.original;
          if (isSystemSkill(s)) {
            return <span className="text-xs text-muted-foreground">read-only</span>;
          }
          return (
            <div className="flex justify-end gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onEdit(s);
                }}
              >
                <Pencil className="w-3 h-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  if (!confirm(`Delete skill "${s.name}"? This cannot be undone.`)) return;
                  del.mutate(s.name, {
                    onSuccess: () => toast.success(`Skill ${s.name} deleted`),
                    onError: (err) =>
                      toast.error(err instanceof Error ? err.message : 'Delete failed'),
                  });
                }}
              >
                <Trash2 className="w-3 h-3" />
              </Button>
            </div>
          );
        },
      },
    ],
    [del, onEdit],
  );

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(s) => s.name}
      onRowClick={(s) => !isSystemSkill(s) && onEdit(s)}
      emptyMessage="No skills yet — click + New Skill to create your first."
      pageSize={50}
    />
  );
}
