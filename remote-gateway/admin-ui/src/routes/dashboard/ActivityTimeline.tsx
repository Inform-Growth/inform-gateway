import {
  LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useTimeline } from '@/hooks/useTimeline';

// Stable palette so the same user keeps the same color across renders.
const USER_COLORS = [
  'var(--primary)',
  'var(--accent)',
  'var(--moss-mid)',
  '#c9755e',
  '#7a8a5f',
  '#b48a52',
];

export function ActivityTimeline() {
  const { data, isLoading } = useTimeline(30);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Activity — Last 30 Days (by user)</CardTitle>
      </CardHeader>
      <CardContent className="h-72">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : !data?.rows.length || !data.users.length ? (
          <p className="text-sm text-muted-foreground py-8 text-center">No calls in the last 30 days.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.rows} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <YAxis stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {data.users.map((user, i) => (
                <Line
                  key={user}
                  type="monotone"
                  dataKey={user}
                  stroke={USER_COLORS[i % USER_COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
