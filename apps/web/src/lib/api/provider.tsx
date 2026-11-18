"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useAuth } from "../auth/provider";
import { ApiClient } from "./client";
import { getApiBaseUrl } from "./config";
import { createEndpoints, type Endpoints } from "./endpoints";

interface ApiContextValue {
  client: ApiClient;
  api: Endpoints;
}

const ApiContext = createContext<ApiContextValue | null>(null);

/** Supplies the typed API. Pass `client` in tests to inject a fake `fetch`. */
export function ApiProvider({ children, client }: { children: ReactNode; client?: ApiClient }) {
  const auth = useAuth();
  const value = useMemo<ApiContextValue>(() => {
    const instance = client ?? new ApiClient({ baseUrl: getApiBaseUrl(), getAuthHeaders: () => auth.getAuthHeaders() });
    return { client: instance, api: createEndpoints(instance) };
  }, [client, auth]);
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>;
}

function useApiContext(): ApiContextValue {
  const value = useContext(ApiContext);
  if (!value) throw new Error("useApi must be used inside <ApiProvider>");
  return value;
}

export function useApi(): Endpoints {
  return useApiContext().api;
}

export function useApiClient(): ApiClient {
  return useApiContext().client;
}
