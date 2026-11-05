import { useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { chatKey, getMessages, type Message } from './chat-data';

export function useOlderMessages(id: string, recent: Message[], recentHasMore: boolean) {
  const [anchor, setAnchor] = useState<{ cursor: string; recent: Message[] }>();
  const older = useInfiniteQuery({
    queryKey: [...chatKey(id), 'before', anchor?.cursor],
    initialPageParam: anchor?.cursor ?? '',
    enabled: Boolean(anchor),
    staleTime: Infinity,
    queryFn: ({ signal, pageParam }) => getMessages(id, signal, pageParam),
    getNextPageParam: (page) => (page.has_more ? page.items[0]?.id : undefined),
  });
  const earlier =
    older.data?.pages
      .slice()
      .reverse()
      .flatMap((page) => page.items) ?? [];
  const items = new Map<string, Message>();
  for (const message of [...earlier, ...(anchor?.recent ?? []), ...recent]) {
    items.set(message.id, message);
  }
  const messages = [...items.values()];
  return {
    messages,
    olderCount: earlier.length,
    hasMore: older.data ? older.hasNextPage : recentHasMore,
    loading: Boolean(anchor) && older.isFetching,
    error: older.error,
    loadMore() {
      if (older.isFetching) return;
      if (older.hasNextPage) void older.fetchNextPage();
      else if (anchor && older.isError) void older.refetch();
      else if (recentHasMore && recent[0]) setAnchor({ cursor: recent[0].id, recent });
    },
  };
}
