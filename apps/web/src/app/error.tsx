"use client";

import { useEffect } from "react";
import { Button, LinkButton } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/feedback";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // Only the digest (a server-side id) is logged: never page content.
    console.error("Unhandled UI error", error.digest ?? error.name);
  }, [error]);
  return (
    <div className="mx-auto max-w-xl py-10">
      <EmptyState
        headingLevel={1}
        icon="alert"
        title="Something went wrong on this screen"
        description={`The screen failed to render. Nothing was lost on the server.${error.digest ? ` Reference: ${error.digest}` : ""}`}
        action={
          <div className="flex flex-wrap justify-center gap-2">
            <Button variant="primary" icon="refresh" onClick={reset}>
              Try again
            </Button>
            <LinkButton href="/" variant="secondary">
              Back to Home
            </LinkButton>
          </div>
        }
      />
    </div>
  );
}
