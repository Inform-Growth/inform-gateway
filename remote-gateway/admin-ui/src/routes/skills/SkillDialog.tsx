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
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { skillSchema, type Skill, type SkillInput } from '@/lib/skillSchema';
import { useCreateSkill, useUpdateSkill } from '@/hooks/useSkills';

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null → create mode; Skill → edit mode. */
  editing: Skill | null;
};

const EMPTY: SkillInput = { name: '', description: '', prompt_template: '' };

export function SkillDialog({ open, onOpenChange, editing }: Props) {
  const create = useCreateSkill();
  const update = useUpdateSkill();
  const isEdit = editing !== null;

  const form = useForm<SkillInput>({
    resolver: zodResolver(skillSchema),
    defaultValues: EMPTY,
  });

  // Hydrate when editing changes; reset to empty when switching to create.
  useEffect(() => {
    form.reset(
      editing
        ? {
            name: editing.name,
            description: editing.description,
            prompt_template: editing.prompt_template,
          }
        : EMPTY,
    );
  }, [editing, form]);

  const onSubmit = (values: SkillInput) => {
    const mut = isEdit ? update : create;
    mut.mutate(values, {
      onSuccess: () => {
        toast.success(isEdit ? 'Skill updated' : 'Skill created');
        onOpenChange(false);
      },
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Save failed'),
    });
  };

  const pending = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${editing.name}` : 'New Skill'}</DialogTitle>
          <DialogDescription>
            Skills are prompt templates rendered at <code>run_skill</code> call time. Use{' '}
            <code>{'{variable}'}</code> placeholders for runtime substitution.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input
                      readOnly={isEdit}
                      placeholder="daily_briefing"
                      className={isEdit ? 'bg-muted text-muted-foreground' : undefined}
                      {...field}
                    />
                  </FormControl>
                  {isEdit && (
                    <FormDescription>Renaming requires recreating the skill.</FormDescription>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="prompt_template"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Prompt Template</FormLabel>
                  <FormControl>
                    <Textarea rows={8} className="font-mono text-xs" {...field} />
                  </FormControl>
                  <FormDescription>
                    Use <code>{'{variable}'}</code> placeholders, filled by the caller of{' '}
                    <code>run_skill</code>.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {pending ? 'Saving…' : isEdit ? 'Save' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
