import { useMemo } from 'react';
import { Sankey, ResponsiveContainer, Tooltip, Layer, Rectangle } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { useSessions } from '@/hooks/useSessions';

type SankeyNodeProps = {
  x: number;
  y: number;
  width: number;
  height: number;
  index: number;
  payload: { name: string; value: number };
  containerWidth: number;
};

function SankeyNode({ x, y, width, height, index, payload, containerWidth }: SankeyNodeProps) {
  const isOut = x + width + 6 > containerWidth;
  return (
    <Layer key={`SankeyNode-${index}`}>
      <Rectangle
        x={x}
        y={y}
        width={width}
        height={height}
        fill="var(--primary)"
        fillOpacity={0.9}
      />
      <text
        textAnchor={isOut ? 'end' : 'start'}
        x={isOut ? x - 6 : x + width + 6}
        y={y + height / 2}
        fontSize="11"
        fill="var(--foreground)"
        dominantBaseline="middle"
      >
        {payload.name}
      </text>
      <text
        textAnchor={isOut ? 'end' : 'start'}
        x={isOut ? x - 6 : x + width + 6}
        y={y + height / 2 + 13}
        fontSize="10"
        fill="var(--muted-foreground)"
        dominantBaseline="middle"
      >
        {payload.value}
      </text>
    </Layer>
  );
}

export function ToolFlowSankey() {
  const { data, isLoading } = useSessions();

  // Recharts <Sankey> requires source/target to be numeric indices into
  // `nodes`, not string ids. The API returns strings, so resolve them here
  // and drop any links that reference an unknown node or self-loops (which
  // produce a disconnected layout).
  const sankeyData = useMemo(() => {
    if (!data?.sankey) return null;
    const { nodes, links } = data.sankey;
    const indexById = new Map(nodes.map((n, i) => [n.id, i]));
    const numericLinks = links.flatMap((l) => {
      const source = indexById.get(l.source);
      const target = indexById.get(l.target);
      if (source === undefined || target === undefined) return [];
      if (source === target) return [];
      return [{ source, target, value: l.value }];
    });
    const usedIdx = new Set<number>();
    numericLinks.forEach((l) => { usedIdx.add(l.source); usedIdx.add(l.target); });
    if (usedIdx.size === nodes.length) return { nodes, links: numericLinks };
    // Drop unused nodes and reindex links to keep the graph connected.
    const keptIndices = [...usedIdx].sort((a, b) => a - b);
    const remap = new Map(keptIndices.map((old, fresh) => [old, fresh]));
    return {
      nodes: keptIndices.map((i) => nodes[i]),
      links: numericLinks.map((l) => ({
        source: remap.get(l.source)!,
        target: remap.get(l.target)!,
        value: l.value,
      })),
    };
  }, [data]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Tool Flow Patterns</CardTitle>
      </CardHeader>
      <CardContent className="h-80">
        {isLoading ? (
          <Skeleton className="h-full w-full" />
        ) : !sankeyData?.links.length ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            Not enough data to draw a flow yet — keep using the gateway.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <Sankey
              data={sankeyData as never /* recharts types are loose */}
              nodePadding={24}
              nodeWidth={12}
              margin={{ top: 8, right: 96, bottom: 8, left: 96 }}
              node={<SankeyNode {...({} as SankeyNodeProps)} />}
              link={{ stroke: 'var(--primary)', strokeOpacity: 0.35 } as never}
            >
              <Tooltip />
            </Sankey>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
