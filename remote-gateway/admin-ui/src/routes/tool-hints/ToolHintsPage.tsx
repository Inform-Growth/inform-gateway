import { useState } from 'react';
import { Plus } from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/button';
import { ToolHintsTable } from './ToolHintsTable';
import { ToolHintDialog } from './ToolHintDialog';
import type { ToolHint } from '@/lib/toolHintSchema';

export default function ToolHintsPage() {
  const [editing, setEditing] = useState<ToolHint | null>(null);
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Tool Hints"
        action={
          <Button
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus className="w-4 h-4 mr-1" /> Add Hint
          </Button>
        }
      />
      <ToolHintsTable
        onEdit={(h) => {
          setEditing(h);
          setOpen(true);
        }}
      />
      <ToolHintDialog open={open} onOpenChange={setOpen} editing={editing} />
    </>
  );
}
