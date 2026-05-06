import { useState } from 'react';
import { PageHeader } from '@/components/layout/PageHeader';
import { useToolCalls, type ToolCall } from '@/hooks/useToolCalls';
import { ToolCallsFilters, useToolCallsFilters } from './ToolCallsFilters';
import { ToolCallsTable } from './ToolCallsTable';
import { ToolCallDetailSheet } from './ToolCallDetailSheet';

export default function ToolCallsPage() {
  const { filters, setFilter, page, setPage } = useToolCallsFilters();
  const { data, isLoading } = useToolCalls(filters);
  const [selected, setSelected] = useState<ToolCall | null>(null);

  return (
    <>
      <PageHeader title="Tool Calls" />
      <ToolCallsFilters filters={filters} setFilter={setFilter} />
      <ToolCallsTable
        data={data ?? []}
        isLoading={isLoading}
        pageSize={filters.limit}
        page={page}
        onPage={setPage}
        onRowClick={setSelected}
      />
      <ToolCallDetailSheet
        call={selected}
        onOpenChange={(open) => { if (!open) setSelected(null); }}
      />
    </>
  );
}
