import { MutationCache, QueryClient } from "@tanstack/react-query";
import { isApiError } from "../api/errors";

export function isRetryable(error: unknown): boolean {
  if (!isApiError(error)) return false;
  return error.kind === "network" || error.kind === "server" || error.kind === "provider_unavailable";
}

/** Prefix of every audit-log query (see qk.audit). */
const AUDIT_KEY = ["safety", "audit"] as const;

declare module "@tanstack/react-query" {
  interface Register {
    mutationMeta: { silent?: boolean };
  }
}

export interface QueryClientOptions {
  /** Called for every failed mutation unless it sets `meta: { silent: true }`. Used to raise accessible toasts. */
  onMutationError?: (error: unknown) => void;
  retry?: boolean;
}

export function createQueryClient({ onMutationError, retry = true }: QueryClientOptions = {}): QueryClient {
  const client: QueryClient = new QueryClient({
    mutationCache: new MutationCache({
      // Every change an owner makes can add an audit entry (block, trust, delete, settings): keep the audit log honest.
      onSuccess: () => {
        void client.invalidateQueries({ queryKey: AUDIT_KEY });
      },
      onError: (error, _variables, _context, mutation) => {
        if (mutation.meta?.silent) return;
        onMutationError?.(error);
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: retry ? (failureCount, error) => failureCount < 2 && isRetryable(error) : false,
      },
      mutations: { retry: false },
    },
  });
  return client;
}
