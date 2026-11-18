import { QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { useEffect, type ReactElement, type ReactNode } from "react";
import { ApiClient } from "@/lib/api/client";
import { ApiProvider } from "@/lib/api/provider";
import { AuthProvider } from "@/lib/auth/provider";
import { createDevAuth } from "@/lib/auth/dev";
import { createQueryClient } from "@/lib/query/client";
import { publishMutationError, subscribeMutationErrors } from "@/lib/query/error-bus";
import { ToastProvider, useToast } from "@/components/ui/toast";
import { createFakeApi, json, type FakeApi } from "./fake-fetch";
import { makeAssistantRoutes } from "./routes";

function MutationErrorToaster() {
  const toast = useToast();
  useEffect(() => subscribeMutationErrors((error) => toast.error(error)), [toast]);
  return null;
}

export interface AppRenderOptions extends Omit<RenderOptions, "wrapper"> {
  api?: FakeApi;
}

export function renderWithApp(ui: ReactElement, { api = createFakeApi(makeAssistantRoutes()), ...options }: AppRenderOptions = {}) {
  const client = new ApiClient({
    baseUrl: "http://api.test",
    fetchImpl: api.fetch,
    getAuthHeaders: () => createDevAuth().getAuthHeaders(),
    createRequestId: () => "req-test",
  });
  const queryClient = createQueryClient({ retry: false, onMutationError: publishMutationError });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ToastProvider>
        <AuthProvider>
          <ApiProvider client={client}>
            <QueryClientProvider client={queryClient}>
              <MutationErrorToaster />
              {children}
            </QueryClientProvider>
          </ApiProvider>
        </AuthProvider>
      </ToastProvider>
    );
  }
  return { api, queryClient, ...render(ui, { wrapper: Wrapper, ...options }) };
}

export { json };
