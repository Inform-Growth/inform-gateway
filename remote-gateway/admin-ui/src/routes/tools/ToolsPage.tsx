import { useState } from 'react';
import { PageHeader } from '@/components/layout/PageHeader';
import { ToolsTable, type MergedTool } from './ToolsTable';
import { ToolDetailSheet } from './ToolDetailSheet';

export default function ToolsPage() {
  const [selected, setSelected] = useState<MergedTool | null>(null);
  return (
    <>
      <PageHeader title="Tools" />
      <ToolsTable onRowClick={setSelected} />
      <ToolDetailSheet tool={selected} onOpenChange={(open) => { if (!open) setSelected(null); }} />
    </>
  );
}
