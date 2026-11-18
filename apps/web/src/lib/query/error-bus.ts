type Listener = (error: unknown) => void;

const listeners = new Set<Listener>();

/** Failed mutations are published here (from the QueryClient's MutationCache) and turned into toasts by <MutationErrorToaster>. */
export function subscribeMutationErrors(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function publishMutationError(error: unknown): void {
  for (const listener of listeners) listener(error);
}
