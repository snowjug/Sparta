"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useApi } from "@/lib/api/provider";
import { downloadBlob } from "@/lib/download";
import { qk } from "@/lib/query/keys";
import { useToast } from "@/components/ui/toast";

/** Export / report downloads and the two deletion flows shared by the history list and the call detail screen. */
export function useCallActions() {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();

  const invalidate = (id?: string) => {
    void queryClient.invalidateQueries({ queryKey: qk.callsRoot });
    void queryClient.invalidateQueries({ queryKey: qk.home });
    if (id) void queryClient.removeQueries({ queryKey: qk.call(id) });
  };

  const exportCall = useMutation({
    mutationFn: async (id: string) => {
      const { blob, filename } = await api.calls.exportJson(id);
      const name = filename ?? `sparta-call-${id}.json`;
      if (!downloadBlob(blob, name)) throw new Error("This browser cannot save files from here.");
      return name;
    },
    onSuccess: (name) => toast.success(`Saved ${name}. It contains the full call, including the transcript, so keep it private.`, { title: "Export ready" }),
  });

  const downloadReport = useMutation({
    mutationFn: async (id: string) => {
      const { blob, filename } = await api.calls.report(id);
      const name = filename ?? `sparta-report-${id}.json`;
      if (!downloadBlob(blob, name)) throw new Error("This browser cannot save files from here.");
      return name;
    },
    onSuccess: (name) => toast.success(`Saved ${name}. It has no transcript text and no phone numbers.`, { title: "Diagnostic report ready" }),
  });

  const deleteContent = useMutation({
    mutationFn: (id: string) => api.calls.deleteContent(id),
    onSuccess: (_result, id) => {
      invalidate();
      void queryClient.invalidateQueries({ queryKey: qk.call(id) });
      toast.success("The transcript, translations and summary text were removed. Time, risk level and category are kept.", { title: "Content deleted" });
    },
  });

  const deleteCall = useMutation({
    mutationFn: (id: string) => api.calls.remove(id),
    onSuccess: (_result, id) => {
      invalidate(id);
      toast.success("The call was removed completely.", { title: "Call deleted" });
    },
  });

  return { exportCall, downloadReport, deleteContent, deleteCall };
}
