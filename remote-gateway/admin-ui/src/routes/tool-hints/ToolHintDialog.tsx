import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  toolHintSchema,
  type ToolHint,
  type ToolHintInput,
  SENSITIVITIES,
} from '@/lib/toolHintSchema';
import { useUpsertToolHint } from '@/hooks/useToolHints';

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: ToolHint | null; // null → new tool name, ToolHint → edit existing
};

const EMPTY: ToolHintInput = {
  tool_name: '',
  interpretation_hint: '',
  usage_rules: '',
  data_sensitivity: 'internal',
};

export function ToolHintDialog({ open, onOpenChange, editing }: Props) {
  const upsert = useUpsertToolHint();
  const isEdit = editing !== null;

  const form = useForm<ToolHintInput>({
    resolver: zodResolver(toolHintSchema),
    defaultValues: EMPTY,
  });

  useEffect(() => {
    form.reset(editing ?? EMPTY);
  }, [editing, form]);

  const onSubmit = (values: ToolHintInput) => {
    upsert.mutate(values, {
      onSuccess: () => {
        toast.success(isEdit ? 'Hint updated' : 'Hint created');
        onOpenChange(false);
      },
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Save failed'),
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Edit hint — ${editing.tool_name}` : 'New Tool Hint'}
          </DialogTitle>
          <DialogDescription>
            Hints are injected into tool responses to guide agent interpretation.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="tool_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tool Name</FormLabel>
                  <FormControl>
                    <Input
                      readOnly={isEdit}
                      className={
                        isEdit
                          ? 'bg-muted text-muted-foreground font-mono text-xs'
                          : 'font-mono text-xs'
                      }
                      placeholder="attio__search_records"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="interpretation_hint"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Interpretation Hint</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormDescription>
                    How should the agent read this tool's output?
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="usage_rules"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Usage Rules</FormLabel>
                  <FormControl>
                    <Textarea rows={3} {...field} />
                  </FormControl>
                  <FormDescription>When and how to call this tool.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="data_sensitivity"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Data Sensitivity</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {SENSITIVITIES.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={upsert.isPending}>
                {upsert.isPending ? 'Saving…' : isEdit ? 'Save' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
