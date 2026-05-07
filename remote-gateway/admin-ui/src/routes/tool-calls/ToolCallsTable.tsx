import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { CheckCircle2, ChevronLeft, ChevronRight, XCircle } from 'lucide-react';
import { DataTable } from '@/components/data-table/DataTable';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type { ToolCall } from '@/hooks/useToolCalls';

type Props = {
  data: ToolCall[];
  isLoading: boolean;
  pageSize: number;
  page: number;
  onPage: (n: number) => void;
  onRowClick: (c: ToolCall) => void;
};

export function ToolCallsTable({ data, isLoading, pageSize, page, onPage, onRowClick }: Props) {
  const columns = useMemo<ColumnDef<ToolCall>[]>(() => [
    {
      accessorKey: 'called_at',
      header: 'Time',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string | null>() ?? '—'}</span>,
    },
    {
      accessorKey: 'tool_name',
      header: 'Tool',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span>,
    },
    {
      accessorKey: 'user_id',
      header: 'User',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string | null>() ?? '—'}</span>,
    },
    {
      accessorKey: 'duration_ms',
      header: 'Duration',
      cell: (c) => `${c.getValue<number>()}ms`,
    },
    {
      accessorKey: 'response_size',
      header: 'Out',
      cell: (c) => {
        const v = c.getValue<number | null>();
        return v == null ? <span className="text-muted-foreground">—</span> : <span>{v}B</span>;
      },
    },
    {
      id: 'status',
      header: 'Status',
      cell: ({ row }) =>
        row.original.success
          ? <CheckCircle2 className="w-4 h-4 text-moss-light" />
          : <XCircle className="w-4 h-4 text-destructive" />,
    },
  ], []);

  if (isLoading && data.length === 0) return <Skeleton className="h-96 w-full" />;

  // The backend returns no count; "next" is enabled when the page is full.
  const hasNext = data.length === pageSize;
  const hasPrev = page > 0;

  return (
    <div className="space-y-2">
      <DataTable
        columns={columns}
        data={data}
        getRowId={(r) => String(r.id)}
        onRowClick={onRowClick}
        pageSize={0}
        emptyMessage="No tool calls match the current filters."
      />
      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>Page {page + 1}</span>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => onPage(page - 1)} disabled={!hasPrev}>
            <ChevronLeft className="w-3 h-3" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => onPage(page + 1)} disabled={!hasNext}>
            <ChevronRight className="w-3 h-3" />
          </Button>
        </div>
      </div>
    </div>
  );
}
