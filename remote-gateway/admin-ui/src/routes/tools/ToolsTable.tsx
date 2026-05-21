import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { DataTable } from '@/components/data-table/DataTable';
import { Skeleton } from '@/components/ui/skeleton';
import { useTools, type ToolMeta } from '@/hooks/useTools';
import { useToolStats, type ToolStat } from '@/hooks/useToolStats';
import { usePermissions, useSetPermission } from '@/hooks/usePermissions';
import { toast } from 'sonner';

export type MergedTool = ToolMeta & Partial<ToolStat> & { enabled: boolean };

const GLOBAL = '*';

export function ToolsTable({ onRowClick }: { onRowClick: (tool: MergedTool) => void }) {
  const tools = useTools();
  const stats = useToolStats();
  const globals = usePermissions(GLOBAL);
  const setGlobal = useSetPermission(GLOBAL);
  const [filter, setFilter] = useState('');

  const merged: MergedTool[] = useMemo(() => {
    const statsByName = new Map((stats.data ?? []).map((s) => [s.name, s]));
    const enabledByName = new Map((globals.data ?? []).map((p) => [p.tool_name, p.enabled]));
    return (tools.data ?? []).map((t) => ({
      ...t,
      ...statsByName.get(t.name),
      enabled: enabledByName.get(t.name) ?? true,
    }));
  }, [tools.data, stats.data, globals.data]);

  const columns = useMemo<ColumnDef<MergedTool>[]>(() => [
    { accessorKey: 'name', header: 'Tool',
      cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    {
      accessorKey: 'description',
      header: 'Description',
      cell: (c) => {
        const v = c.getValue<string>();
        return v
          ? <div className="text-sm whitespace-normal max-w-xl">{v}</div>
          : <span className="text-muted-foreground">—</span>;
      },
    },
    { accessorKey: 'call_count', header: 'Calls',
      cell: (c) => c.getValue<number | undefined>() ?? <span className="text-muted-foreground">—</span> },
    { accessorKey: 'error_rate', header: 'Errors',
      cell: (c) => c.getValue<string | undefined>() ?? <span className="text-muted-foreground">—</span> },
    { accessorKey: 'last_called', header: 'Last Called',
      cell: (c) => c.getValue<string | null | undefined>() ?? <span className="text-muted-foreground">—</span> },
    {
      id: 'enabled',
      header: 'Global',
      cell: ({ row }) => (
        // base-ui Switch renders a <span role="switch"> + a sibling <input> outside it.
        // Its onClick dispatches a secondary PointerEvent on that input, which bubbles past
        // the [role="switch"] guard in DataTable. Wrapping both elements in a div and
        // stopping propagation here catches both events before they reach the TableRow.
        <div onClick={(e) => e.stopPropagation()}>
          <Switch
            checked={row.original.enabled}
            onCheckedChange={(enabled) => {
              setGlobal.mutate(
                { tool_name: row.original.name, enabled },
                {
                  onSuccess: () =>
                    toast.success(`${row.original.name} ${enabled ? 'enabled' : 'disabled'}`),
                  onError: (err) =>
                    toast.error(err instanceof Error ? err.message : 'Failed to toggle'),
                },
              );
            }}
          />
        </div>
      ),
    },
  ], [setGlobal]);

  if (tools.isLoading || globals.isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="space-y-3">
      <Input
        placeholder="Filter tools by name or description…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="max-w-sm"
      />
      <DataTable
        columns={columns}
        data={merged}
        getRowId={(t) => t.name}
        onRowClick={onRowClick}
        emptyMessage={
          filter
            ? 'No tools match the filter.'
            : 'No tools registered. Configure mcp_connections.json to add proxied integrations.'
        }
        pageSize={50}
        initialSorting={[{ id: 'call_count', desc: true }]}
        globalFilter={filter}
      />
    </div>
  );
}
