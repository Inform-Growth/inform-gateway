import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { DataTable } from '@/components/data-table/DataTable';
import { useToolHints } from '@/hooks/useToolHints';
import type { ToolHint } from '@/lib/toolHintSchema';

const sensitivityVariant: Record<string, 'default' | 'secondary' | 'destructive'> = {
  public: 'secondary',
  internal: 'default',
  sensitive: 'destructive',
};

export function ToolHintsTable({ onEdit }: { onEdit: (h: ToolHint) => void }) {
  const { data, isLoading } = useToolHints();

  const columns = useMemo<ColumnDef<ToolHint>[]>(
    () => [
      {
        accessorKey: 'tool_name',
        header: 'Tool',
        cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span>,
      },
      {
        accessorKey: 'interpretation_hint',
        header: 'Interpretation',
        cell: (c) => {
          const v = c.getValue<string>();
          return v ? (
            <span className="text-sm">{v}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          );
        },
      },
      {
        accessorKey: 'data_sensitivity',
        header: 'Sensitivity',
        cell: (c) => {
          const v = c.getValue<string>();
          return <Badge variant={sensitivityVariant[v] ?? 'default'}>{v}</Badge>;
        },
      },
      {
        id: 'actions',
        header: '',
        cell: ({ row }) => (
          <div className="flex justify-end">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={(e) => {
                e.stopPropagation();
                onEdit(row.original);
              }}
            >
              <Pencil className="w-3 h-3" />
            </Button>
          </div>
        ),
      },
    ],
    [onEdit],
  );

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(h) => h.tool_name}
      onRowClick={onEdit}
      emptyMessage="No tool hints yet. Add one to guide agent interpretation."
      pageSize={50}
    />
  );
}
