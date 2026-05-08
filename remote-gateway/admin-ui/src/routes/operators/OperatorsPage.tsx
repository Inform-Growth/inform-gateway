import { useState } from 'react';
import { PageHeader } from '@/components/layout/PageHeader';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { OperatorsTable } from './OperatorsTable';
import { PermissionsPanel } from './PermissionsPanel';
import { SkillPermissionsPanel } from './SkillPermissionsPanel';
import { AddOperatorDialog } from './AddOperatorDialog';

export default function OperatorsPage() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Operators" action={<AddOperatorDialog />} />
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_24rem] gap-6">
        <OperatorsTable selectedUserId={selected} onSelect={setSelected} />
        <Tabs defaultValue="tools" className="min-w-0">
          <TabsList>
            <TabsTrigger value="tools">Tools</TabsTrigger>
            <TabsTrigger value="skills">Skills</TabsTrigger>
          </TabsList>
          <TabsContent value="tools">
            <PermissionsPanel userId={selected} />
          </TabsContent>
          <TabsContent value="skills">
            <SkillPermissionsPanel userId={selected} />
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
