import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage,
} from '@/components/ui/form';
import { useOrgProfile, useUpdateOrgProfile } from '@/hooks/useOrgProfile';
import { orgProfileSchema, type OrgProfile } from '@/lib/orgProfileSchema';

export default function SettingsPage() {
  const { data, isLoading, isError } = useOrgProfile();
  const update = useUpdateOrgProfile();

  const form = useForm<OrgProfile>({
    resolver: zodResolver(orgProfileSchema),
    defaultValues: { display_name: '', tone: '', icp: '', vocab_rules: '' },
  });

  // Hydrate the form when the query resolves.
  useEffect(() => {
    if (data) form.reset(data);
  }, [data, form]);

  const onSubmit = (values: OrgProfile) => {
    update.mutate(values, {
      onSuccess: () => toast.success('Settings saved'),
      onError: (err) => toast.error(err instanceof Error ? err.message : 'Save failed'),
    });
  };

  if (isError) {
    return (
      <>
        <PageHeader title="Settings" />
        <Card>
          <CardContent className="pt-6 text-destructive">
            Failed to load org profile. Refresh to retry.
          </CardContent>
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Settings"
        action={
          <Button
            type="submit"
            form="settings-form"
            disabled={!form.formState.isDirty || update.isPending}
          >
            {update.isPending ? 'Saving…' : 'Save'}
          </Button>
        }
      />

      {isLoading ? (
        <SettingsSkeleton />
      ) : (
        <Form {...form}>
          <form id="settings-form" onSubmit={form.handleSubmit(onSubmit)} className="space-y-6 max-w-2xl">
            <Card>
              <CardHeader>
                <CardTitle>Org Identity</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="display_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Display Name</FormLabel>
                      <FormControl>
                        <Input placeholder="Acme Corp" {...field} />
                      </FormControl>
                      <FormDescription>How the org appears in the dashboard header.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Voice</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="tone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tone</FormLabel>
                      <FormControl>
                        <Input placeholder="professional, concise" {...field} />
                      </FormControl>
                      <FormDescription>Writing style for agents acting on behalf of this org.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="icp"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>ICP</FormLabel>
                      <FormControl>
                        <Input placeholder="B2B SaaS, 10-200 employees" {...field} />
                      </FormControl>
                      <FormDescription>Ideal customer profile — informs prospecting and outreach skills.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="vocab_rules"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Vocabulary Rules</FormLabel>
                      <FormControl>
                        <Textarea
                          rows={5}
                          placeholder="Always say 'prospect' not 'lead'…"
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>One rule per line. Applied to all generated text.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CardContent>
            </Card>
          </form>
        </Form>
      )}
    </>
  );
}

function SettingsSkeleton() {
  return (
    <div className="space-y-6 max-w-2xl">
      <Card>
        <CardHeader><Skeleton className="h-5 w-32" /></CardHeader>
        <CardContent><Skeleton className="h-9 w-full" /></CardContent>
      </Card>
      <Card>
        <CardHeader><Skeleton className="h-5 w-24" /></CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
