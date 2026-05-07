import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DataTable } from '@/components/data-table/DataTable';
import { useOperators, useDeleteOperator, type Operator } from '@/hooks/useOperators';
import { Skeleton } from '@/components/ui/skeleton';
import { toast } from 'sonner';

export function OperatorsTable({
  selectedUserId,
  onSelect,
}: {
  selectedUserId: string | null;
  onSelect: (userId: string) => void;
}) {
  const { data, isLoading } = useOperators();
  const del = useDeleteOperator();

  const columns = useMemo<ColumnDef<Operator>[]>(() => [
    { accessorKey: 'user_id', header: 'User ID' },
    { accessorKey: 'key', header: 'Key', cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    { accessorKey: 'call_count', header: 'Calls' },
    {
      accessorKey: 'last_active',
      header: 'Last Active',
      cell: (c) => {
        const v = c.getValue<string | null>();
        return v ?? <span className="text-muted-foreground">—</span>;
      },
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={(e) => {
            e.stopPropagation();
            const id = row.original.user_id;
            if (!confirm(`Revoke API access for ${id}? This cannot be undone.`)) return;
            del.mutate(id, {
              onSuccess: () => toast.success(`Operator ${id} revoked`),
              onError: (err) => toast.error(err instanceof Error ? err.message : 'Revoke failed'),
            });
          }}
        >
          <Trash2 className="w-3 h-3" />
        </Button>
      ),
    },
  ], [del]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;

  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(o) => o.user_id}
      onRowClick={(o) => onSelect(o.user_id)}
      selectedRowId={selectedUserId ?? undefined}
      emptyMessage="No operators yet — add one to get started."
      pageSize={25}
    />
  );
}
