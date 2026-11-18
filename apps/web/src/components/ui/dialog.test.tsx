import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog, Dialog } from "./dialog";
import { findOpenDialog } from "@/test/dialog";

describe("Dialog", () => {
  it("wraps Tab and Shift+Tab inside the dialog, so focus never reaches the page behind or the browser UI", async () => {
    render(
      <>
        <button type="button">Behind the dialog</button>
        <Dialog open onClose={() => undefined} title="Pick one" footer={<button type="button">Last</button>}>
          <input aria-label="Middle" />
        </Dialog>
      </>,
    );
    const dialog = await findOpenDialog();
    const close = within(dialog).getByRole("button", { name: "Close dialog" });
    const last = within(dialog).getByRole("button", { name: "Last" });

    last.focus();
    await userEvent.tab();
    expect(close).toHaveFocus(); // forward from the last control wraps to the first

    await userEvent.tab({ shift: true });
    expect(last).toHaveFocus(); // backward from the first control wraps to the last

    await userEvent.tab({ shift: true });
    expect(within(dialog).getByLabelText("Middle")).toHaveFocus(); // everything in between is normal tab order
    expect(screen.getByText("Behind the dialog")).not.toHaveFocus();
  });

  it("closes on Escape and when the backdrop is clicked", async () => {
    const onClose = vi.fn();
    render(
      <Dialog open onClose={onClose} title="Close me">
        <p>Body</p>
      </Dialog>,
    );
    const dialog = await findOpenDialog();
    dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("ConfirmDialog", () => {
  it("enables the confirm button only after the required word is typed, and keeps the dialog open when the action fails", async () => {
    const onConfirm = vi.fn(async () => Promise.reject(new Error("nope")));
    render(<ConfirmDialog open onClose={() => undefined} title="Delete it?" confirmLabel="Delete everything" requireText="delete" onConfirm={onConfirm} />);
    const dialog = await findOpenDialog();
    const confirm = within(dialog).getByRole("button", { name: "Delete everything" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/Type .delete. to confirm/), "Delete");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(dialog).toHaveAttribute("open");
  });
});
