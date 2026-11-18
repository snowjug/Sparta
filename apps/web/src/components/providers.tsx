"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { ApiProvider } from "@/lib/api/provider";
import { AuthProvider } from "@/lib/auth/provider";
import { createQueryClient } from "@/lib/query/client";
import { publishMutationError, subscribeMutationErrors } from "@/lib/query/error-bus";
import { ToastProvider, useToast } from "@/components/ui/toast";

/** Failed mutations raise an accessible toast (with a copyable trace id) unless they opt out with meta.silent. */
function MutationErrorToaster() {
  const toast = useToast();
  useEffect(() => subscribeMutationErrors((error) => toast.error(error)), [toast]);
  return null;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => createQueryClient({ onMutationError: publishMutationError }));
  return (
    <ToastProvider>
      <AuthProvider>
        <ApiProvider>
          <QueryClientProvider client={queryClient}>
            <MutationErrorToaster />
            {children}
          </QueryClientProvider>
        </ApiProvider>
      </AuthProvider>
    </ToastProvider>
  );
}
