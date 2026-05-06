import { useEffect, useState } from 'react';
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import type { ToolCall } from '@/hooks/useToolCalls';

type Props = {
  call: ToolCall | null;
  onOpenChange: (open: boolean) => void;
};

function tryPretty(json: string | null): string {
  if (!json) return '—';
  try { return JSON.stringify(JSON.parse(json), null, 2); } catch { return json; }
}

export function ToolCallDetailSheet({ call, onOpenChange }: Props) {
  // Stage the last non-null call so the close animation doesn't flash blank.
  const [staged, setStaged] = useState(call);
  useEffect(() => { if (call) setStaged(call); }, [call]);
  const c = call ?? staged;

  return (
    <Sheet open={!!call} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-2xl overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="font-mono text-sm flex items-center gap-2">
            {c?.tool_name}
            {c?.success === false && <Badge variant="destructive">error</Badge>}
            {c?.success === true && <Badge variant="secondary">ok</Badge>}
          </SheetTitle>
          <SheetDescription>
            {c?.called_at ?? '—'} · {c?.duration_ms ?? 0}ms · user {c?.user_id ?? '—'}
          </SheetDescription>
        </SheetHeader>

        {c && (
          <div className="space-y-6 mt-6 text-sm">
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Metadata
              </h3>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">Request ID</dt>
                <dd className="font-mono text-xs">{c.request_id ?? '—'}</dd>
                <dt className="text-muted-foreground">Task ID</dt>
                <dd className="font-mono text-xs">{c.task_id ?? '—'}</dd>
                <dt className="text-muted-foreground">Input size</dt>
                <dd>{c.input_size ?? '—'} bytes</dd>
                <dt className="text-muted-foreground">Response size</dt>
                <dd>{c.response_size ?? '—'} bytes</dd>
              </dl>
            </section>

            {c.success === false && (
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Error
                </h3>
                <div className="p-3 bg-destructive/10 text-destructive font-mono text-xs rounded">
                  <div className="font-bold">{c.error_type ?? 'unknown'}</div>
                  <div className="mt-1 whitespace-pre-wrap">{c.error_message ?? '(no message)'}</div>
                </div>
              </section>
            )}

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Request body
              </h3>
              <ScrollArea className="h-48 rounded border border-border">
                <pre className="p-3 font-mono text-xs whitespace-pre-wrap break-all">
                  {tryPretty(c.input_body)}
                </pre>
              </ScrollArea>
            </section>

            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                Response preview
              </h3>
              <ScrollArea className="h-48 rounded border border-border">
                <pre className="p-3 font-mono text-xs whitespace-pre-wrap break-all">
                  {c.response_preview ?? '—'}
                </pre>
              </ScrollArea>
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
