import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageHeader } from '@/components/layout/PageHeader';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { TasksTable } from './TasksTable';
import { TaskDetailSheet } from './TaskDetailSheet';
import type { Task } from '@/hooks/useTasks';

const ALL = '__all__';

export default function TasksPage() {
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState<Task | null>(null);

  const status = (params.get('status') ?? '') as '' | 'active' | 'complete';

  const setStatus = (next: string) => {
    const p = new URLSearchParams(params);
    if (next && next !== ALL) p.set('status', next); else p.delete('status');
    setParams(p, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Tasks"
        action={
          <Select value={status || ALL} onValueChange={(v) => setStatus(v ?? '')}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="complete">Complete</SelectItem>
            </SelectContent>
          </Select>
        }
      />
      <TasksTable filters={{ status: status || undefined, limit: 200 }} onRowClick={setSelected} />
      <TaskDetailSheet
        task={selected}
        onOpenChange={(open) => { if (!open) setSelected(null); }}
      />
    </>
  );
}
