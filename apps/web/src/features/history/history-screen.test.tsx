import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HistoryScreen, parseFilters } from "./history-screen";
import { renderWithApp } from "@/test/render";
import { apiError, createFakeApi } from "@/test/fake-fetch";
import { makeCallItem } from "@/test/fixtures";
import { makeAssistantRoutes } from "@/test/routes";
import { findOpenDialog } from "@/test/dialog";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), pathname: "/calls", search: "" }));
vi.mock("next/navigation", () => {
  const cache = new Map<string, URLSearchParams>();
  return {
    useRouter: () => ({ push: nav.push, replace: nav.replace, back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
    usePathname: () => nav.pathname,
    useSearchParams: () => {
      if (!cache.has(nav.search)) cache.set(nav.search, new URLSearchParams(nav.search));
      return cache.get(nav.search)!;
    },
  };
});

function routes(items = [makeCallItem()], extra: Record<string, () => unknown> = {}) {
  return createFakeApi({
    ...makeAssistantRoutes(),
    "GET /api/v1/calls": () => ({ items, next_cursor: null }),
    ...extra,
  });
}

describe("parseFilters", () => {
  it("accepts only known values and converts the date range to ISO instants", () => {
    const filters = parseFilters(new URLSearchParams("q=bank&risk_level=high&category=telemarketing&language=hi-IN&status=ended&attention=1&from=2026-11-01&to=2026-11-17&junk=1"));
    expect(filters).toMatchObject({ q: "bank", risk_level: "high", category: "telemarketing", language: "hi-IN", status: "ended", attention: true });
    expect(filters.from).toMatch(/^2026-1[01]-/);
    expect(filters.to).toMatch(/^2026-11-1[78]/);
    expect(parseFilters(new URLSearchParams("risk_level=nuclear&category=x&status=weird&language=<script>&from=yesterday"))).toEqual({});
  });
});

describe("HistoryScreen", () => {
  it("lists calls with privacy-preserving caller display, summary and badges", async () => {
    nav.search = "";
    renderWithApp(<HistoryScreen />, { api: routes([makeCallItem({ id: "c1" }), makeCallItem({ id: "c2", caller_display: "Private number", risk_level: "low", summary_text: "A courier asked for directions." })]) });
    const rows = await screen.findAllByTestId("history-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByTestId("caller-display")).toHaveTextContent("+91 98•••• ••21");
    expect(within(rows[1]!).getByText("A courier asked for directions.")).toBeInTheDocument();
    expect(within(rows[0]!).getAllByText("Simulated").length).toBeGreaterThan(0);
    expect(screen.getByTestId("history-count")).toHaveTextContent("2 calls shown");
  });

  it("sends the filters to the API: search (debounced), risk, status, attention", async () => {
    nav.search = "";
    nav.replace.mockClear();
    const api = routes();
    const { rerender } = renderWithApp(<HistoryScreen />, { api });
    await screen.findAllByTestId("history-row");

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "bank" } });
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/calls?q=bank", { scroll: false }), { timeout: 2000 });

    nav.search = "q=bank&risk_level=high&status=ended&attention=1";
    rerender(<HistoryScreen />);
    await waitFor(() => {
      const last = api.callsTo("GET /api/v1/calls").at(-1)!;
      expect(Object.fromEntries(last.query.entries())).toMatchObject({ q: "bank", risk_level: "high", status: "ended", attention: "true", limit: "20" });
    });

    await userEvent.selectOptions(screen.getByLabelText("Risk"), "medium");
    expect(nav.replace).toHaveBeenCalledWith(expect.stringContaining("risk_level=medium"), { scroll: false });
  });

  it("keeps every filter when several change before the router has committed the first URL", async () => {
    nav.search = "language=hi-IN";
    nav.replace.mockClear();
    const { rerender } = renderWithApp(<HistoryScreen />, { api: routes() });
    await screen.findAllByTestId("history-row");

    // The mocked router never commits: the committed URL stays "language=hi-IN" while the owner keeps changing filters.
    await userEvent.selectOptions(screen.getByLabelText("Language"), "");
    await userEvent.selectOptions(screen.getByLabelText("Risk"), "high");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "ended");
    const urls = nav.replace.mock.calls.map((call) => String(call[0]));
    expect(urls[0]).toBe("/calls"); // the language filter was removed
    expect(urls[1]).toBe("/calls?risk_level=high"); // and that removal is not undone by the next change
    expect(urls[2]).toBe("/calls?risk_level=high&status=ended");

    // Once the router commits something else (back button, a link), the committed URL wins again.
    nav.search = "category=telemarketing";
    nav.replace.mockClear();
    rerender(<HistoryScreen />);
    await userEvent.selectOptions(screen.getByLabelText("Risk"), "low");
    expect(nav.replace).toHaveBeenLastCalledWith("/calls?category=telemarketing&risk_level=low", { scroll: false });
  });

  it("loads more with the cursor", async () => {
    nav.search = "";
    const api = createFakeApi({
      ...makeAssistantRoutes(),
      "GET /api/v1/calls": (req) =>
        req.query.get("cursor") === "next-1"
          ? { items: [makeCallItem({ id: "c3", summary_text: "Third call" })], next_cursor: null }
          : { items: [makeCallItem({ id: "c1" }), makeCallItem({ id: "c2" })], next_cursor: "next-1" },
    });
    renderWithApp(<HistoryScreen />, { api });
    await screen.findAllByTestId("history-row");
    await userEvent.click(screen.getByTestId("load-more"));
    expect(await screen.findByText("Third call")).toBeInTheDocument();
    expect(screen.getAllByTestId("history-row")).toHaveLength(3);
    expect(screen.queryByTestId("load-more")).toBeNull();
    expect(screen.getByText("That's every call that matches.")).toBeInTheDocument();
  });

  it("explains an empty history and an empty search result differently", async () => {
    nav.search = "";
    const { unmount } = renderWithApp(<HistoryScreen />, { api: routes([]) });
    expect(await screen.findByText("No calls yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run a simulated call/ })).toHaveAttribute("href", "/simulator");
    unmount();

    nav.search = "q=zzz";
    renderWithApp(<HistoryScreen />, { api: routes([]) });
    expect(await screen.findByText("No calls match these filters")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Clear filters/ }).length).toBeGreaterThan(0);
  });

  it("shows an error state with a way to retry", async () => {
    nav.search = "";
    let fail = true;
    const api = routes([], { "GET /api/v1/calls": () => (fail ? apiError(503, "provider_unavailable", "Database interruption", { trace_id: "trace-xyz" }) : { items: [makeCallItem()], next_cursor: null }) });
    renderWithApp(<HistoryScreen />, { api });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Database interruption");
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("history-row")).toBeInTheDocument();
  });

  it("expands a row, exports it, and deletes the content only after confirmation", async () => {
    nav.search = "";
    const api = routes([makeCallItem({ id: "c1" })], {
      "GET /api/v1/calls/c1/export": () => new Response('{"id":"c1"}', { headers: { "Content-Disposition": 'attachment; filename="sparta-call-c1.json"' } }),
      "DELETE /api/v1/calls/c1/content": () => undefined,
    });
    URL.createObjectURL = vi.fn(() => "blob:fake");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWithApp(<HistoryScreen />, { api });
    const row = await screen.findByTestId("history-row");
    await userEvent.click(within(row).getByRole("button", { expanded: false }));
    expect(within(row).getByTestId("history-details")).toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Export JSON" }));
    await waitFor(() => expect(api.callsTo("GET /api/v1/calls/c1/export")).toHaveLength(1));
    await waitFor(() => expect(click).toHaveBeenCalled());

    await userEvent.click(within(row).getByRole("button", { name: "Delete content" }));
    const dialog = await findOpenDialog();
    expect(api.callsTo("DELETE /api/v1/calls/c1/content")).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete content" }));
    await waitFor(() => expect(api.callsTo("DELETE /api/v1/calls/c1/content")).toHaveLength(1));
    click.mockRestore();
  });

  it("deletes a whole call after confirmation and never offers deletion for a call in progress", async () => {
    nav.search = "";
    const api = routes([makeCallItem({ id: "c1" }), makeCallItem({ id: "live", status: "active", state: "ASSESSING", ended_at: null, duration_ms: null })], { "DELETE /api/v1/calls/c1": () => undefined });
    renderWithApp(<HistoryScreen />, { api });
    const rows = await screen.findAllByTestId("history-row");
    await userEvent.click(within(rows[1]!).getByRole("button", { expanded: false }));
    expect(within(rows[1]!).queryByRole("button", { name: "Delete call" })).toBeNull();
    expect(within(rows[1]!).getByRole("link", { name: "Open live view" })).toHaveAttribute("href", "/live/live");

    await userEvent.click(within(rows[0]!).getByRole("button", { expanded: false }));
    await userEvent.click(within(rows[0]!).getByRole("button", { name: "Delete call" }));
    const dialog = await findOpenDialog();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete call" }));
    await waitFor(() => expect(api.callsTo("DELETE /api/v1/calls/c1")).toHaveLength(1));
  });
});
