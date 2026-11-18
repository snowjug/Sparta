/** `matchMedia` for jsdom. Pass the queries that should match, e.g. `{ "(prefers-reduced-motion: reduce)": true }`. */
export function mockMatchMedia(matching: Record<string, boolean> = {}): void {
  const impl = (query: string): MediaQueryList =>
    ({
      matches: matching[query] ?? false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
  Object.defineProperty(window, "matchMedia", { writable: true, configurable: true, value: impl });
}

/** A canvas context that accepts every call; lets VoiceStage run its drawing code without a real canvas. */
export function installFakeCanvas(): { draws: () => number } {
  let draws = 0;
  const context = new Proxy(
    {},
    {
      get: (_target, property) => {
        if (property === "clearRect") return () => (draws += 1);
        return () => {};
      },
      set: () => true,
    },
  );
  HTMLCanvasElement.prototype.getContext = (() => context) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  return { draws: () => draws };
}
