import { useState } from 'react';
import { PageHeader } from '@/components/layout/PageHeader';
import { OperatorsTable } from './OperatorsTable';
import { PermissionsPanel } from './PermissionsPanel';
import { AddOperatorDialog } from './AddOperatorDialog';

export default function OperatorsPage() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Operators" action={<AddOperatorDialog />} />
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_24rem] gap-6">
        <OperatorsTable selectedUserId={selected} onSelect={setSelected} />
        <PermissionsPanel userId={selected} />
      </div>
    </>
  );
}
