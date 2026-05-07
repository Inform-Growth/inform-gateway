import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { DataTable } from '@/components/data-table/DataTable';
import { useTasks, type Task, type TasksFilters } from '@/hooks/useTasks';

function formatRel(ts: number | string): string {
  const t = typeof ts === 'string' ? Date.parse(ts) / 1000 : ts;
  const diff = Math.round(Date.now() / 1000 - t);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function durationStr(start: number | string, end: number | string | null): string {
  if (end == null) return '—';
  const s = typeof start === 'string' ? Date.parse(start) / 1000 : start;
  const e = typeof end === 'string' ? Date.parse(end) / 1000 : end;
  const sec = Math.max(0, Math.round(e - s));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

export function TasksTable({
  filters,
  onRowClick,
}: {
  filters: TasksFilters;
  onRowClick: (t: Task) => void;
}) {
  const { data, isLoading } = useTasks(filters);

  const columns = useMemo<ColumnDef<Task>[]>(() => [
    {
      accessorKey: 'goal',
      header: 'Goal',
      cell: (c) => <span className="text-sm">{c.getValue<string>()}</span>,
    },
    {
      accessorKey: 'user_id',
      header: 'User',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span>,
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) =>
        row.original.status === 'active'
          ? <Badge>active</Badge>
          : <Badge variant="secondary">complete</Badge>,
    },
    {
      accessorKey: 'created_at',
      header: 'Created',
      cell: (c) => <span className="text-muted-foreground text-xs">{formatRel(c.getValue<number | string>())}</span>,
    },
    {
      id: 'duration',
      header: 'Duration',
      cell: ({ row }) => (
        <span className="text-muted-foreground text-xs">
          {durationStr(row.original.created_at, row.original.completed_at)}
        </span>
      ),
    },
  ], []);

  if (isLoading) return <Skeleton className="h-96 w-full" />;
  return (
    <DataTable
      columns={columns}
      data={data ?? []}
      getRowId={(t) => t.task_id}
      onRowClick={onRowClick}
      emptyMessage="No tasks match the current filter."
      pageSize={50}
    />
  );
}
