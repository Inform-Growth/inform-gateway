import { useSearchParams } from 'react-router-dom';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import type { ToolCallFilters } from '@/hooks/useToolCalls';

const ALL = '__all__';

export function useToolCallsFilters(): {
  filters: ToolCallFilters;
  setFilter: (key: 'tool' | 'user' | 'success', value: string) => void;
  page: number;
  setPage: (n: number) => void;
} {
  const [params, setParams] = useSearchParams();

  const tool = params.get('tool') ?? '';
  const user = params.get('user') ?? '';
  const success = (params.get('success') ?? '') as '' | 'true' | 'false';
  const page = Number(params.get('page') ?? '0');
  const pageSize = 50;

  const setFilter = (key: 'tool' | 'user' | 'success', value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    next.delete('page'); // reset paging when filters change
    setParams(next, { replace: true });
  };

  const setPage = (n: number) => {
    const next = new URLSearchParams(params);
    if (n > 0) next.set('page', String(n)); else next.delete('page');
    setParams(next, { replace: true });
  };

  return {
    filters: {
      limit: pageSize,
      offset: page * pageSize,
      tool: tool || undefined,
      user: user || undefined,
      success: success || undefined,
    },
    setFilter,
    page,
    setPage,
  };
}

export function ToolCallsFilters({
  filters,
  setFilter,
}: {
  filters: ToolCallFilters;
  setFilter: (key: 'tool' | 'user' | 'success', value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      <Input
        placeholder="Filter by tool…"
        defaultValue={filters.tool ?? ''}
        onBlur={(e) => setFilter('tool', e.target.value.trim())}
        onKeyDown={(e) => {
          if (e.key === 'Enter') setFilter('tool', (e.target as HTMLInputElement).value.trim());
        }}
        className="font-mono text-xs max-w-xs"
      />
      <Input
        placeholder="Filter by user…"
        defaultValue={filters.user ?? ''}
        onBlur={(e) => setFilter('user', e.target.value.trim())}
        onKeyDown={(e) => {
          if (e.key === 'Enter') setFilter('user', (e.target as HTMLInputElement).value.trim());
        }}
        className="font-mono text-xs max-w-xs"
      />
      <Select
        value={filters.success || ALL}
        onValueChange={(v) => setFilter('success', !v || v === ALL ? '' : v)}
      >
        <SelectTrigger className="w-40">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All statuses</SelectItem>
          <SelectItem value="true">Success only</SelectItem>
          <SelectItem value="false">Errors only</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}
