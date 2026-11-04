import { Download } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import type { components } from '@/api/schema';
import { useSession, sessionKey } from '@/features/auth/use-session';
import { Button } from '@/components/ui/button';
import type { ProjectFile } from '@/features/workspace/file-tree-data';
import { useProjectBlob } from './material-queries';

export function DownloadFile({ id, file }: { id: string; file: ProjectFile }) {
  const query = useProjectBlob(id, file, false);
  const client = useQueryClient();
  const { data: session } = useSession();
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={query.isFetching}
      onClick={() => {
        void query.refetch().then((result) => {
          if (
            !result.data ||
            result.isError ||
            !session?.user.id ||
            client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id !==
              session.user.id
          )
            return;
          const url = URL.createObjectURL(result.data);
          const anchor = document.createElement('a');
          anchor.href = url;
          anchor.download = file.path.split('/').at(-1) ?? 'material';
          anchor.click();
          setTimeout(() => URL.revokeObjectURL(url), 30_000);
        });
      }}
    >
      <Download className="size-4" aria-hidden="true" />
      Скачать файл
    </Button>
  );
}
