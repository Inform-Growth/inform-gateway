import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { toast } from 'sonner';
import { Copy, Plus, Check } from 'lucide-react';
import { useCreateOperator } from '@/hooks/useOperators';

export function AddOperatorDialog() {
  const [open, setOpen] = useState(false);
  const [userId, setUserId] = useState('');
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const create = useCreateOperator();

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate(userId, {
      onSuccess: ({ key }) => setCreatedKey(key),
      onError: (err) =>
        toast.error(err instanceof Error ? err.message : 'Failed to create operator'),
    });
  };

  const reset = () => {
    setUserId('');
    setCreatedKey(null);
    setCopied(false);
  };

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) reset();
  };

  const copyKey = async () => {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger render={<Button />}>
        <Plus className="w-4 h-4 mr-1" /> Add Operator
      </DialogTrigger>
      <DialogContent>
        {createdKey ? (
          <>
            <DialogHeader>
              <DialogTitle>Operator created</DialogTitle>
              <DialogDescription>
                Copy this API key now — it won't be shown again.
              </DialogDescription>
            </DialogHeader>
            <Alert>
              <AlertTitle className="font-mono break-all text-xs">{createdKey}</AlertTitle>
              <AlertDescription>
                Provide this key to the operator out of band (1Password, Slack DM, etc).
              </AlertDescription>
            </Alert>
            <DialogFooter>
              <Button variant="outline" onClick={copyKey}>
                {copied ? <Check className="w-4 h-4 mr-1" /> : <Copy className="w-4 h-4 mr-1" />}
                {copied ? 'Copied' : 'Copy key'}
              </Button>
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={onSubmit}>
            <DialogHeader>
              <DialogTitle>Add operator</DialogTitle>
              <DialogDescription>
                The operator will get a fresh API key for connecting to the gateway.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-2 my-4">
              <Label htmlFor="op-user-id">User ID</Label>
              <Input
                id="op-user-id"
                autoFocus
                placeholder="alice@example.com"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!userId.trim() || create.isPending}>
                {create.isPending ? 'Creating…' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
