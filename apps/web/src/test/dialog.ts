import { waitFor } from "@testing-library/react";

/** The native <dialog> elements are always in the DOM (closed ones are hidden): wait for the one that is open. */
export async function findOpenDialog(): Promise<HTMLElement> {
  return waitFor(() => {
    const dialog = document.querySelector<HTMLElement>("dialog[open]");
    if (!dialog) throw new Error("no dialog is open");
    return dialog;
  });
}
