import { useState } from 'react';
import { Plus } from 'lucide-react';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/button';
import { SkillsTable } from './SkillsTable';
import { SkillDialog } from './SkillDialog';
import type { Skill } from '@/lib/skillSchema';

export default function SkillsPage() {
  const [editing, setEditing] = useState<Skill | null>(null);
  const [open, setOpen] = useState(false);

  const openCreate = () => {
    setEditing(null);
    setOpen(true);
  };
  const openEdit = (s: Skill) => {
    setEditing(s);
    setOpen(true);
  };

  return (
    <>
      <PageHeader
        title="Skills"
        action={
          <Button onClick={openCreate}>
            <Plus className="w-4 h-4 mr-1" /> New Skill
          </Button>
        }
      />
      <SkillsTable onEdit={openEdit} />
      <SkillDialog open={open} onOpenChange={setOpen} editing={editing} />
    </>
  );
}
