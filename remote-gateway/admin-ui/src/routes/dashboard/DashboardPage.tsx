import { PageHeader } from '@/components/layout/PageHeader';
import { KPICards } from './KPICards';
import { ToolFlowSankey } from './ToolFlowSankey';
import { ActivityTimeline } from './ActivityTimeline';
import { UserAdoptionChart } from './UserAdoptionChart';
import { ToolHealthTable } from './ToolHealthTable';

export default function DashboardPage() {
  return (
    <>
      <PageHeader title="Dashboard" />
      <KPICards />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
        <ToolFlowSankey />
        <UserAdoptionChart />
      </div>
      <div className="mb-8">
        <ActivityTimeline />
      </div>
      <ToolHealthTable />
    </>
  );
}
