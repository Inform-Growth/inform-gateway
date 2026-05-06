import {
  LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useTimeline } from '@/hooks/useTimeline';

export function ActivityTimeline() {
  const { data, isLoading } = useTimeline(30);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Activity — Last 30 Days</CardTitle>
      </CardHeader>
      <CardContent className="h-72">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : !data?.totals.length ? (
          <p className="text-sm text-muted-foreground py-8 text-center">No calls in the last 30 days.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.totals} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <YAxis stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="total" stroke="var(--primary)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
