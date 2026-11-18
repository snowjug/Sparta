"use client";

import { useState } from "react";
import { useDevUser } from "@/lib/auth/provider";
import { isValidDevUser } from "@/lib/auth/dev";
import { useMe, useSystemStatus } from "@/lib/query/hooks";
import { getAuthMode } from "@/lib/api/config";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, TextInput } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";

/**
 * Persistent "Development identity" banner. It has no dismiss control on purpose: while the API runs with dev
 * authentication (no credentials) every screen must say so. Hidden only when the API reports dev_banner:false.
 */
export function DevBanner() {
  const { data: status } = useSystemStatus();
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const visible = status ? status.dev_banner : getAuthMode() === "dev";
  if (!visible) return null;

  return (
    <aside aria-label="Development identity" data-testid="dev-banner" className="border-b border-warning/40 bg-warning-bg text-warning">
      <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5 text-sm sm:px-6">
        <Icon name="key" size={16} className="shrink-0" />
        <p className="min-w-0 flex-1 font-medium">
          <strong className="font-semibold">Development identity</strong>
          <span className="text-fg">
            {" "}
            · {me ? <>you are <span className="font-mono text-[0.8125rem]">{me.id}</span>, signed in without credentials.</> : "no credentials are used."}{" "}
            <span className="hidden sm:inline">Not for production.</span>
          </span>
        </p>
        <Button variant="ghost" size="sm" className="-my-1 text-fg" onClick={() => setOpen(true)}>
          Switch identity
        </Button>
      </div>
      <SwitchIdentityDialog open={open} onClose={() => setOpen(false)} />
    </aside>
  );
}

function SwitchIdentityDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { devUser, setDevUser } = useDevUser();
  const [value, setValue] = useState(devUser ?? "");
  const trimmed = value.trim();
  const valid = trimmed === "" || isValidDevUser(trimmed);

  function apply(next: string | null) {
    setDevUser(next);
    // A different owner sees different data: drop every cached response by reloading.
    window.location.reload();
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Switch development identity"
      description="Sends the X-Sparta-Dev-User header so you can check that each owner only sees their own calls. Leave empty for the API default."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          {devUser ? (
            <Button variant="secondary" onClick={() => apply(null)}>
              Use API default
            </Button>
          ) : null}
          <Button variant="primary" disabled={!valid || trimmed === (devUser ?? "")} onClick={() => apply(trimmed || null)}>
            Switch
          </Button>
        </>
      }
    >
      <Field label="Identity" hint="Letters, digits, dot, dash or underscore (max 40)." error={valid ? undefined : "Use only letters, digits, '.', '_' or '-'."}>
        {(props) => (
          <TextInput
            {...props}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="dev-owner"
            data-autofocus
          />
        )}
      </Field>
    </Dialog>
  );
}
