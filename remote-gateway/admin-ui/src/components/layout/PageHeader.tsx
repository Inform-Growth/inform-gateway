export function PageHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="sticky top-0 z-10 bg-background py-4 border-b border-border flex items-center justify-between mb-6">
      <h2 className="font-serif text-2xl font-bold">{title}</h2>
      {action}
    </div>
  );
}
