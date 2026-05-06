import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { setToken } from '@/lib/auth';

export default function LoginPage() {
  const [t, setT] = useState('');
  return (
    <div className="flex h-screen items-center justify-center">
      <form
        className="bg-card border border-border p-8 max-w-sm w-full space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          setToken(t);
          window.location.href = '/admin/dashboard';
        }}
      >
        <h1 className="font-serif text-xl font-bold">Admin Token</h1>
        <Input value={t} onChange={(e) => setT(e.target.value)} placeholder="Paste admin token" />
        <Button type="submit" className="w-full">Continue</Button>
      </form>
    </div>
  );
}
