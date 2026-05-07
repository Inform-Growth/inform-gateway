import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { DataTable } from '@/components/data-table/DataTable';
import { useToolStats, type ToolStat } from '@/hooks/useToolStats';

export function ToolHealthTable() {
  const { data, isLoading } = useToolStats();

  const columns = useMemo<ColumnDef<ToolStat>[]>(() => [
    { accessorKey: 'name', header: 'Tool',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    { accessorKey: 'call_count', header: 'Calls' },
    { accessorKey: 'error_count', header: 'Errors' },
    {
      accessorKey: 'error_rate',
      header: 'Error Rate',
      cell: ({ row }) => {
        const rate = row.original.error_rate ?? '0.0%';
        const numeric = parseFloat(rate);
        return numeric >= 5
          ? <Badge variant="destructive">{rate}</Badge>
          : <span className="text-sm">{rate}</span>;
      },
    },
    { accessorKey: 'avg_duration_ms', header: 'Avg ms' },
    { accessorKey: 'max_duration_ms', header: 'Max ms' },
    {
      accessorKey: 'last_called',
      header: 'Last Called',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string | null>() ?? '—'}</span>,
    },
  ], []);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tool Health</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <DataTable
            columns={columns}
            data={data ?? []}
            getRowId={(t) => t.name}
            emptyMessage="No tool calls recorded yet."
            pageSize={25}
            initialSorting={[{ id: 'call_count', desc: true }]}
          />
        )}
      </CardContent>
    </Card>
  );
}
