import type { Metadata } from "next";
import { LinkButton } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/feedback";

export const metadata: Metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl py-10">
      <EmptyState
        headingLevel={1}
        icon="search"
        title="That page doesn't exist"
        description="The link may be old, or the call may have been deleted."
        action={
          <LinkButton href="/" variant="primary">
            Back to Home
          </LinkButton>
        }
      />
    </div>
  );
}
