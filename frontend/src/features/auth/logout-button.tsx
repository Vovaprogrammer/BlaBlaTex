import { LogOut } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { api } from '@/api/client';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { replaceSession } from './session-actions';

export function LogoutButton() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const logout = useMutation({
    mutationFn: () => api.POST('/api/v1/auth/logout'),
    onSuccess: async () => {
      await replaceSession(client, null);
      navigate('/login', { replace: true });
    },
  });
  return (
    <div className="min-w-0 lg:mt-auto">
      <Button
        variant="ghost"
        disabled={logout.isPending}
        onClick={() => logout.mutate()}
        className="min-h-11 justify-start px-4 text-base"
      >
        <LogOut aria-hidden="true" />
        {logout.isPending ? 'Выходим…' : 'Выйти'}
      </Button>
      {logout.isError && (
        <p role="alert" className="mt-2 break-words text-sm text-destructive">
          {errorMessage(logout.error)}
        </p>
      )}
    </div>
  );
}
