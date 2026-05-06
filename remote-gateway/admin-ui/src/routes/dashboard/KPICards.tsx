import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useStatsSummary } from '@/hooks/useStatsSummary';
import { useToolStats } from '@/hooks/useToolStats';

function KPI({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">{label}</div>
        <div className="text-3xl font-serif font-bold">{value}</div>
        {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
      </CardContent>
    </Card>
  );
}

export function KPICards() {
  const summary = useStatsSummary();
  const stats = useToolStats();

  if (summary.isLoading || stats.isLoading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
      </div>
    );
  }

  const totalCalls = summary.data?.total_calls ?? 0;
  const toolsSeen = summary.data?.total_tools_seen ?? 0;
  const highErrorCount = summary.data?.high_error_rate.length ?? 0;
  const avgLatency = (() => {
    const tools = stats.data ?? [];
    if (tools.length === 0) return 0;
    const totalCallsWeighted = tools.reduce((s, t) => s + (t.avg_duration_ms ?? 0) * t.call_count, 0);
    const totalCallsAll = tools.reduce((s, t) => s + t.call_count, 0);
    return totalCallsAll > 0 ? Math.round(totalCallsWeighted / totalCallsAll) : 0;
  })();

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      <KPI label="Total Calls" value={totalCalls.toLocaleString()} />
      <KPI label="Tools Tracked" value={toolsSeen} />
      <KPI
        label="High Error Rate"
        value={highErrorCount}
        hint={highErrorCount > 0 ? 'tools with ≥5% errors' : 'no problem tools'}
      />
      <KPI label="Avg Latency" value={`${avgLatency}ms`} hint="weighted by call count" />
    </div>
  );
}
