import { Sankey, ResponsiveContainer, Tooltip } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useSessions } from '@/hooks/useSessions';

export function ToolFlowSankey() {
  const { data, isLoading } = useSessions();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tool Flow Patterns</CardTitle>
      </CardHeader>
      <CardContent className="h-80">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : !data?.sankey.links.length ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            Not enough data to draw a flow yet — keep using the gateway.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <Sankey
              data={data.sankey as never /* recharts wants numeric source/target indices */}
              nodePadding={20}
              link={{ stroke: 'var(--moss-mid)' } as never}
              node={{
                fill: 'var(--primary)',
                stroke: 'var(--border)',
              } as never /* recharts types are loose here */}
            >
              <Tooltip />
            </Sankey>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
