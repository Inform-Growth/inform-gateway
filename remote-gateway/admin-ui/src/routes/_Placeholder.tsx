import { PageHeader } from '@/components/layout/PageHeader';

export function Placeholder({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <p className="text-muted-foreground">Coming soon — this page is under construction.</p>
    </>
  );
}
