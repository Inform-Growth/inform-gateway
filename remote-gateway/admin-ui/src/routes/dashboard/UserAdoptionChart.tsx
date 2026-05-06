import {
  BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useSessions } from '@/hooks/useSessions';

export function UserAdoptionChart() {
  const { data, isLoading } = useSessions();
  const breakdown = Object.entries(data?.user_breakdown ?? {})
    .map(([user, calls]) => ({ user, calls }))
    .sort((a, b) => b.calls - a.calls)
    .slice(0, 10); // top 10 users

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">User Adoption</CardTitle>
      </CardHeader>
      <CardContent className="h-72">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : breakdown.length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">No user activity yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={breakdown} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="user" stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <YAxis stroke="var(--muted-foreground)" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="calls" fill="var(--accent)" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
