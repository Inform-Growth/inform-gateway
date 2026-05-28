import { useEffect, useState } from 'react';
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import { CheckCircle2, XCircle } from 'lucide-react';
import { useToolCalls } from '@/hooks/useToolCalls';
import type { Task } from '@/hooks/useTasks';
import { cn } from '@/lib/utils';

type Props = {
  task: Task | null;
  onOpenChange: (open: boolean) => void;
};

function formatTs(ts: number | string | null): string {
  if (ts == null) return '—';
  if (typeof ts === 'string') return ts;
  return new Date(ts * 1000).toISOString().replace('.000Z', 'Z');
}

function durationStr(start: number | string, end: number | string | null): string {
  if (end == null) return 'in progress';
  const s = typeof start === 'string' ? Date.parse(start) / 1000 : start;
  const e = typeof end === 'string' ? Date.parse(end) / 1000 : end;
  const sec = Math.max(0, Math.round(e - s));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

export function TaskDetailSheet({ task, onOpenChange }: Props) {
  const [staged, setStaged] = useState(task);
  useEffect(() => { if (task) setStaged(task); }, [task]);
  const t = task ?? staged;

  const calls = useToolCalls({
    limit: 100,
    offset: 0,
    task_id: t?.task_id,
  });

  return (
    <Sheet open={!!task} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {t?.goal ?? 'Task'}
            {t?.status === 'active' && <Badge>active</Badge>}
            {t?.status === 'complete' && <Badge variant="secondary">complete</Badge>}
          </SheetTitle>
          <SheetDescription>
            {t?.user_id ?? '—'} · {t?.task_id ?? '—'}
          </SheetDescription>
        </SheetHeader>

        {t && (
          <div className="space-y-6 mt-6 text-sm">
            {/* Timeline */}
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Timeline
              </h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">Created</dt>
                <dd className="font-mono text-xs">{formatTs(t.created_at)}</dd>
                <dt className="text-muted-foreground">Completed</dt>
                <dd className="font-mono text-xs">{formatTs(t.completed_at)}</dd>
                <dt className="text-muted-foreground">Duration</dt>
                <dd>{durationStr(t.created_at, t.completed_at)}</dd>
              </dl>
            </section>

            {/* Decision context */}
            {(t.decision_context || t.decision_type || t.stakes_hint) && (
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Decision context
                </h3>
                <div className="space-y-2">
                  {(t.decision_type || t.stakes_hint) && (
                    <div className="flex items-center gap-2 flex-wrap">
                      {t.decision_type && (
                        <Badge variant={t.decision_type === 'decision' ? 'default' : 'secondary'}>
                          {t.decision_type}
                        </Badge>
                      )}
                      {t.stakes_hint && (
                        <Badge
                          variant="outline"
                          className={cn(
                            t.stakes_hint === 'high' && 'border-destructive text-destructive',
                            t.stakes_hint === 'medium' && 'border-yellow-500 text-yellow-600 dark:text-yellow-400',
                            t.stakes_hint === 'low' && 'border-muted-foreground text-muted-foreground',
                          )}
                        >
                          {t.stakes_hint} stakes
                        </Badge>
                      )}
                    </div>
                  )}
                  {t.decision_context && (
                    <p className="text-sm text-muted-foreground leading-relaxed">
                      {t.decision_context}
                    </p>
                  )}
                </div>
              </section>
            )}

            {/* Planned steps */}
            {t.steps && t.steps.length > 0 && (
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Planned steps ({t.steps.length})
                </h3>
                <ol className="space-y-1 list-decimal list-inside">
                  {t.steps.map((step, i) => (
                    <li key={i} className="text-sm text-muted-foreground leading-snug">
                      {step}
                    </li>
                  ))}
                </ol>
              </section>
            )}

            {/* Outcome */}
            {t.outcome && (
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Outcome
                </h3>
                <ScrollArea className="max-h-32 rounded border border-border">
                  <p className="p-3 text-sm whitespace-pre-wrap">{t.outcome}</p>
                </ScrollArea>
              </section>
            )}

            {/* Tool calls */}
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Tool calls ({calls.data?.length ?? 0})
              </h3>
              {calls.isLoading ? (
                <Skeleton className="h-32 w-full" />
              ) : !calls.data?.length ? (
                <p className="text-sm text-muted-foreground">
                  No tool calls recorded for this task.
                </p>
              ) : (
                <div className="rounded border border-border divide-y divide-border max-h-96 overflow-y-auto">
                  {calls.data.map((c) => (
                    <div key={c.id} className="px-3 py-2 flex items-center gap-3 text-xs">
                      {c.success
                        ? <CheckCircle2 className="w-3 h-3 text-moss-light shrink-0" />
                        : <XCircle className="w-3 h-3 text-destructive shrink-0" />}
                      <span className="font-mono truncate flex-1">{c.tool_name}</span>
                      <span className="text-muted-foreground shrink-0">{c.duration_ms}ms</span>
                      <span className="text-muted-foreground font-mono shrink-0 text-[10px]">{c.called_at}</span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
