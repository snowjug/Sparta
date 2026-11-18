import { readFileSync } from "node:fs";
import { SCENARIO_TURNS } from "./support/api";
import { startLabCall, sendTypedTurn, waitForAssistantToFinish } from "./support/lab";
import { FAKE_SPEECH_RECOGNITION, silentWav, SPY_SPEECH_SYNTHESIS } from "./support/media";
import { expect, test } from "./support/test";
import { notifications, toggleSwitch } from "./support/ui";

// Simulator Lab: everything the brief lists for screen H, against the real backend.

test.describe("setup, scenarios and providers", () => {
  test("lists the curated scenarios, honest provider status and a SIMULATED badge", async ({ page, api }) => {
    await page.goto("/simulator");
    const scenarios = await api.get<Array<{ id: string; title: string }>>("simulator/scenarios");
    expect(scenarios.length).toBeGreaterThanOrEqual(10);
    await expect(page.getByTestId("scenario-option")).toHaveCount(scenarios.length + 1); // + free play
    for (const id of ["bank-otp-en", "language-switch-journey", "delivery-legit", "unsupported-tamil"]) {
      await expect(page.locator(`[data-testid="scenario-option"][data-scenario-id="${id}"]`)).toBeVisible();
    }
    await expect(page.getByText("Simulated", { exact: true }).first()).toBeVisible();

    await page.locator("summary", { hasText: "Provider status" }).click();
    const providers = await api.get<Array<{ id: string; active: boolean; simulated: boolean }>>("simulator/providers");
    await expect(page.getByTestId("provider-item")).toHaveCount(providers.length);
    const active = page.locator('[data-testid="provider-item"][data-active="true"]');
    await expect(active.first()).toContainText(/simulat/i);
  });

  test("a custom scenario can be built, reordered and stored by the API", async ({ page, api }) => {
    await page.goto("/simulator");
    await page.locator("summary", { hasText: "Custom scenario builder" }).click();
    const builder = page.getByTestId("scenario-builder");
    await expect(builder.getByTestId("create-scenario")).toBeDisabled();
    await builder.getByTestId("scenario-title").fill("E2E custom OTP scam");
    await builder.getByTestId("scenario-turn-text").first().fill("This is the fraud team. Please read out the OTP now.");
    await builder.getByTestId("add-turn").click();
    await builder.getByTestId("scenario-turn-text").nth(1).fill("Hurry, your account will be blocked today.");
    await builder.getByRole("button", { name: "Move turn 2 up" }).click();
    await expect(builder.getByTestId("scenario-turn-text").first()).toHaveValue("Hurry, your account will be blocked today.");
    await builder.getByTestId("create-scenario").click();

    await expect(notifications(page)).toContainText("Scenario created");
    const stored = (await api.get<Array<{ id: string; title: string; custom: boolean; turn_count: number }>>("simulator/scenarios")).find((s) => s.title === "E2E custom OTP scam");
    expect(stored).toMatchObject({ custom: true, turn_count: 2 });
    const option = page.locator(`[data-testid="scenario-option"][data-scenario-id="${stored!.id}"]`);
    await expect(option).toContainText("Yours");
    await expect(option.locator("input")).toBeChecked();
  });
});

test.describe("playing the caller", () => {
  test("typed turns, language and network selectors, idempotency key, event log and diagnostics with simulated stages", async ({ page, api }) => {
    const posts: Array<{ url: string; key: string | null }> = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/v1/")) posts.push({ url: request.url(), key: request.headers()["idempotency-key"] ?? null });
    });
    const callId = await startLabCall(page, { language: "hi-IN", network: "congested" });
    await waitForAssistantToFinish(api, callId);
    await sendTypedTurn(page, "Namaste, main bank se bol raha hoon, aapka account band ho jayega.");
    await expect(page.locator('[data-testid="turn"][data-speaker="caller"]')).toHaveCount(1);
    await expect(page.locator('[data-testid="turn"][data-speaker="caller"]').first()).toHaveAttribute("data-language", "hi-IN");

    // Every create/mutation POST carries an Idempotency-Key.
    const created = posts.filter((p) => /\/(simulator\/calls|calls\/[^/]+\/turns)$/.test(p.url));
    expect(created.length).toBeGreaterThanOrEqual(2);
    expect(created.every((p) => p.key && /^[A-Za-z0-9_:.-]{1,64}$/.test(p.key))).toBe(true);

    // Diagnostics: the congested profile adds latency that is flagged as simulated.
    await page.locator("summary", { hasText: "Diagnostics" }).click();
    const stages = page.getByTestId("latency-stage");
    await expect(stages.first()).toBeVisible();
    await expect(page.locator('[data-testid="latency-stage"][data-simulated="true"]').first()).toContainText("simulated");
    await expect(page.getByTestId("diagnostics")).toContainText("Connected");
    await expect(page.getByTestId("trace-id")).not.toBeEmpty();

    // Event log: real events, filterable, with raw JSON on demand.
    await page.locator("summary", { hasText: "Event log" }).click();
    await expect(page.locator('[data-testid="event-row"][data-type="transcript.final"]').first()).toBeVisible();
    await expect(page.locator('[data-testid="event-row"][data-type="assistant.speaking"]').first()).toBeVisible();
    await page.getByLabel("Show", { exact: true }).selectOption("transcript");
    await expect(page.locator('[data-testid="event-row"]:not([data-type^="transcript."])')).toHaveCount(0);
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download events" }).click()]);
    expect(download.suggestedFilename()).toBe(`sparta-events-${callId}.json`);
  });

  test("barge-in interrupts the assistant and marks the interrupted turn; the silence button fires one silence timeout", async ({ page, api }) => {
    const callId = await startLabCall(page);
    const bargeIn = page.getByTestId("barge-in");
    await expect(bargeIn).toBeEnabled(); // the intro is being spoken
    await bargeIn.click();
    await expect(notifications(page)).toContainText("Barge-in");
    await expect(page.getByTestId("turn").first()).toContainText("Interrupted");
    await expect(bargeIn).toBeDisabled();
    expect((await api.getCall(callId)).turns[0]?.interrupted).toBe(true);

    const before = await page.getByTestId("turn").count();
    await page.getByTestId("caller-silent").click();
    await expect(page.getByTestId("turn")).toHaveCount(before + 1);
    await expect(page.getByTestId("turn").last()).toHaveAttribute("data-speaker", "assistant");
  });

  test("a caller turn typed while the assistant is speaking is barge-in and the call state still advances", async ({ page, api }) => {
    const callId = await startLabCall(page);
    await sendTypedTurn(page, "Hello, I am calling from your bank.");
    await expect(page.locator('[data-testid="turn"][data-speaker="caller"]')).toHaveCount(1);
    await expect(page.getByTestId("turn").first()).toContainText("Interrupted");
    const call = await api.getCall(callId);
    expect(call.turns.find((turn) => turn.speaker === "assistant")?.interrupted).toBe(true);
    expect(call.state).not.toBe("GREETING");
  });
});

test.describe("audio upload", () => {
  // The browser logs the 422 it receives; the test provokes it on purpose.
  test.use({ allowedErrors: /status of 422/ });

  test("without a transcript hint the simulator answers 422 stt_unavailable and the explanation is shown inline", async ({ page, api }) => {
    const callId = await startLabCall(page);
    const response = await api.request.post(`calls/${callId}/audio`, { multipart: { file: { name: "caller.wav", mimeType: "audio/wav", buffer: silentWav() } } });
    expect(response.status()).toBe(422);
    const apiMessage = (await response.json()).error.message as string;
    expect(apiMessage.length).toBeGreaterThan(20);

    await page.getByTestId("audio-file").setInputFiles({ name: "caller.wav", mimeType: "audio/wav", buffer: silentWav() });
    await page.getByTestId("upload-audio").click();
    const problem = page.getByTestId("audio-problem");
    await expect(problem).toBeVisible();
    await expect(problem).toContainText(apiMessage);
    // Nothing was added to the transcript.
    await expect(page.locator('[data-testid="turn"][data-speaker="caller"]')).toHaveCount(0);
  });

  test("with a transcript hint the clip is accepted and becomes a caller turn; wrong types are refused before upload", async ({ page, api }) => {
    const callId = await startLabCall(page);
    await waitForAssistantToFinish(api, callId);

    await page.getByTestId("audio-file").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("not audio") });
    await expect(page.getByTestId("audio-problem")).toContainText("Unsupported file type");
    await expect(page.getByTestId("upload-audio")).toBeDisabled();

    await page.getByTestId("audio-file").setInputFiles({ name: "caller.wav", mimeType: "audio/wav", buffer: silentWav() });
    await page.getByTestId("transcript-hint").fill("I am calling from the bank about your account.");
    await page.getByTestId("upload-audio").click();
    await expect(page.locator('[data-testid="turn"][data-speaker="caller"]')).toHaveCount(1);
    await expect(page.locator('[data-testid="turn"][data-speaker="caller"]').first()).toContainText("calling from the bank");
    await expect(page.getByTestId("audio-problem")).toHaveCount(0);
  });
});

test.describe("microphone and browser speech", () => {
  test("without the Web Speech API the Lab says so clearly and typing still works", async ({ page }) => {
    await page.addInitScript("delete window.SpeechRecognition; delete window.webkitSpeechRecognition;");
    await startLabCall(page);
    await expect(page.getByTestId("mic-unsupported")).toContainText("no speech recognition");
    await expect(page.getByTestId("mic-start")).toHaveCount(0);
    await expect(page.getByTestId("caller-text")).toBeEnabled();
  });

  test.describe("with a scriptable recognizer and Chromium's fake microphone", () => {
    test.use({ permissions: ["microphone"] });

    test("interim text goes to /partial, the final sentence to /turns as browser_stt with its confidence, in the selected language", async ({ page, api }) => {
      await page.addInitScript({ content: FAKE_SPEECH_RECOGNITION });
      const callId = await startLabCall(page, { language: "hi-IN" });
      await waitForAssistantToFinish(api, callId);

      const partials: unknown[] = [];
      const turns: unknown[] = [];
      page.on("request", (request) => {
        if (request.method() !== "POST") return;
        if (request.url().endsWith(`/calls/${callId}/partial`)) partials.push(request.postDataJSON());
        if (request.url().endsWith(`/calls/${callId}/turns`)) turns.push(request.postDataJSON());
      });

      await page.getByTestId("mic-start").click();
      await expect(page.getByTestId("mic-status")).toHaveText("Listening…");
      expect(await page.evaluate(() => (window as unknown as { __recognitionLangs: string[] }).__recognitionLangs.at(-1))).toBe("hi-IN");

      // The stage is driven by the real analyser on the fake microphone while it listens.
      await page.evaluate(() => (window as unknown as { __recognition: { emit: (t: string, f: boolean) => void } }).__recognition.emit("main bank se", false));
      await expect(page.getByTestId("partial-turn")).toContainText("main bank se");
      await page.evaluate(() => (window as unknown as { __recognition: { emit: (t: string, f: boolean, c: number) => void } }).__recognition.emit("main bank se bol raha hoon", true, 0.87));
      await expect(page.locator('[data-testid="turn"][data-speaker="caller"]')).toHaveCount(1);
      await expect(page.locator('[data-testid="turn"][data-speaker="caller"]').first()).toContainText("main bank se bol raha hoon");

      expect(partials[0]).toMatchObject({ text: "main bank se", language_hint: "hi-IN" });
      expect(turns[0]).toMatchObject({ text: "main bank se bol raha hoon", source: "browser_stt", language_hint: "hi-IN" });
      expect((turns[0] as { stt_confidence: number }).stt_confidence).toBeCloseTo(0.87, 2);

      await page.getByTestId("mic-stop").click();
      await expect(page.getByTestId("mic-status")).toHaveText("Microphone is off");
    });

    test("a recogniser error is explained, not swallowed", async ({ page }) => {
      await page.addInitScript({ content: FAKE_SPEECH_RECOGNITION });
      await startLabCall(page);
      await page.getByTestId("mic-start").click();
      await expect(page.getByTestId("mic-status")).toHaveText("Listening…");
      await page.evaluate(() => {
        const rec = (window as unknown as { __recognition: { onerror: (e: { error: string }) => void } }).__recognition;
        rec.onerror({ error: "not-allowed" });
      });
      await expect(page.getByTestId("mic-error")).toContainText("Microphone permission was denied");
      await expect(page.getByTestId("mic-status")).toHaveText("Stopped");
    });
  });

  test("'Hear the assistant' is labelled as the BROWSER voice and speaks the assistant's reply with the browser's synthesiser", async ({ page, api }) => {
    await page.addInitScript({ content: SPY_SPEECH_SYNTHESIS });
    const callId = await startLabCall(page);
    await waitForAssistantToFinish(api, callId);
    const toggle = page.getByRole("switch", { name: /Hear the assistant \(BROWSER voice\)/ });
    await expect(toggle).toBeVisible();
    await expect(page.getByText(/not the production voice/i)).toBeVisible();
    await toggleSwitch(page, /Hear the assistant \(BROWSER voice\)/);
    await expect(toggle).toBeChecked();
    await sendTypedTurn(page, "Hello, who am I speaking with at your end?");
    await expect.poll(() => page.evaluate(() => (window as unknown as { __spoken: Array<{ text: string }> }).__spoken.length)).toBeGreaterThan(0);
    const spoken = await page.evaluate(() => (window as unknown as { __spoken: Array<{ text: string; lang: string }> }).__spoken);
    expect(spoken[0]?.lang).toMatch(/^en/);
    const assistantReply = (await api.getCall(callId)).turns.filter((turn) => turn.speaker === "assistant").at(-1)?.text;
    expect(spoken.map((item) => item.text)).toContain(assistantReply);
  });
});

test.describe("honest voice stage", () => {
  test("a scripted call plays to the end and the stage follows its live events: assistant speaking, caller speaking, ended", async ({ page, api }) => {
    test.setTimeout(120_000);
    const callId = await startLabCall(page, { scenario: "bank-otp-en", autoplay: true });
    const result = page.getByTestId("lab-console");
    await page.evaluate(() => {
      // One observer on the whole document: React may re-create the stage or the transcript while the call runs.
      const modes: string[] = [];
      const flags = { partial: false, labels: [] as string[] };
      const sample = () => {
        const mode = document.querySelector('[data-testid="voice-stage"]')?.getAttribute("data-mode") ?? "";
        if (mode && modes.at(-1) !== mode) modes.push(mode);
        if (document.querySelector('[data-testid="partial-turn"]')) flags.partial = true;
        const label = document.querySelector('[data-testid="voice-stage-label"]')?.textContent ?? "";
        if (label && flags.labels.at(-1) !== label) flags.labels.push(label);
      };
      sample();
      new MutationObserver(sample).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["data-mode"] });
      Object.assign(window, { __modes: modes, __flags: flags });
    });

    await expect(result).toHaveAttribute("data-status", "ended", { timeout: 90_000 });
    const { modes, flags } = await page.evaluate(() => ({ modes: (window as unknown as { __modes: string[] }).__modes, flags: (window as unknown as { __flags: { partial: boolean; labels: string[] } }).__flags }));
    expect(modes).toContain("assistant_speaking");
    expect(modes).toContain("caller_speaking");
    expect(modes.at(-1)).toBe("ended");
    expect(modes.filter((mode) => mode === "ended")).toHaveLength(1);
    expect(flags.partial).toBe(true);
    // The label is a text equivalent of the animation: every state change is also announced in words.
    expect(flags.labels.join(" | ")).toMatch(/speaking/i);

    // The server played the whole script on its own and reached the outcome the scenario promises: risk high, refusal, hang-up, summary.
    await expect(page.getByTestId("risk-meter")).toHaveAttribute("data-risk", /^(high|critical)$/);
    await expect(result).toHaveAttribute("data-state", "COMPLETED");
    await expect(page.getByTestId("turn").last()).toContainText("I can't share or accept any personal, financial or security information");
    await expect(page.getByTestId("lab-summary")).toBeVisible({ timeout: 15_000 });
    await expect.poll(async () => (await api.getCall(callId)).status, { timeout: 30_000 }).toBe("ended");
    const call = await api.getCall(callId);
    expect(call.turns.filter((turn) => turn.speaker === "caller").map((turn) => turn.text)).toEqual([...SCENARIO_TURNS["bank-otp-en"]]);
    expect(call.turns.at(-1)?.speaker).toBe("assistant");
    expect(call.risk?.risk_level).toMatch(/^(high|critical)$/);
    expect(call.action_taken).toBe("refused_and_ended");
    expect(call.summary?.text).toBeTruthy();
  });

  test("with reduced motion the stage stops animating but still shows every state in words", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript(() => {
      const frames = { count: 0 };
      const original = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (callback) => {
        frames.count += 1;
        return original(callback);
      };
      Object.assign(window, { __frames: frames });
    });
    await startLabCall(page);
    const stage = page.getByTestId("voice-stage");
    await expect(stage).toHaveAttribute("data-reduced-motion", "true");
    await expect(stage).toHaveAttribute("data-mode", "assistant_speaking");
    await expect(page.getByTestId("voice-stage-label")).toContainText("Sparta is speaking");
    const before = await page.evaluate(() => (window as unknown as { __frames: { count: number } }).__frames.count);
    await page.waitForTimeout(1200);
    const after = await page.evaluate(() => (window as unknown as { __frames: { count: number } }).__frames.count);
    expect(after - before).toBeLessThanOrEqual(3);
  });

  test("with normal motion the same stage animates every frame while the assistant speaks", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.addInitScript(() => {
      const frames = { count: 0 };
      const original = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (callback) => {
        frames.count += 1;
        return original(callback);
      };
      Object.assign(window, { __frames: frames });
    });
    await startLabCall(page);
    await expect(page.getByTestId("voice-stage")).toHaveAttribute("data-reduced-motion", "false");
    await expect(page.getByTestId("voice-stage")).toHaveAttribute("data-mode", "assistant_speaking");
    const before = await page.evaluate(() => (window as unknown as { __frames: { count: number } }).__frames.count);
    await page.waitForTimeout(1200);
    const after = await page.evaluate(() => (window as unknown as { __frames: { count: number } }).__frames.count);
    expect(after - before).toBeGreaterThan(20);
  });
});

test.describe("scenario coverage", () => {
  test("the language-switch scenario plays itself in real time: each language change shows up live, then refusal, end and summary", async ({ page, api }) => {
    test.setTimeout(150_000);
    const callId = await startLabCall(page, { scenario: "language-switch-journey", autoplay: true });
    const console = page.getByTestId("lab-console");
    const callerTurns = page.locator('[data-testid="turn"][data-speaker="caller"]');
    await expect(console).toHaveAttribute("data-status", "active");

    // Live, not after the fact: the first caller turn is on screen while the call is still running.
    await expect(callerTurns.first()).toHaveAttribute("data-language", "en-IN", { timeout: 30_000 });
    await expect(console).toHaveAttribute("data-status", "active");

    await expect(console).toHaveAttribute("data-status", "ended", { timeout: 120_000 });
    await expect(callerTurns).toHaveCount(SCENARIO_TURNS["language-switch-journey"].length);
    await expect(callerTurns.nth(1)).toHaveAttribute("data-language", "hi-IN");
    await expect(callerTurns.nth(1)).toContainText("Hinglish");
    await expect(callerTurns.nth(2)).toContainText("Kanglish");
    await expect(page.getByTestId("language-change").first()).toContainText("English → Hindi");
    await expect(page.getByTestId("language-change").nth(1)).toContainText("Kannada");
    await expect(page.getByTestId("risk-meter")).toHaveAttribute("data-risk", /^(high|critical)$/);
    await expect(console).toHaveAttribute("data-state", "COMPLETED");
    await expect(page.getByTestId("turn").last()).toContainText("I can't share or accept any personal, financial or security information");
    await expect(page.getByTestId("lab-summary")).toBeVisible({ timeout: 15_000 });

    const call = await api.getCall(callId);
    expect(call.turns.filter((turn) => turn.speaker === "caller").map((turn) => turn.text)).toEqual([...SCENARIO_TURNS["language-switch-journey"]]);
    expect(call.risk?.risk_level).toMatch(/^(high|critical)$/);
    expect(call.action_taken).toBe("refused_and_ended");
    expect(call.summary?.text).toBeTruthy();
  });

  test("an unsupported language is handled honestly (unsupported-tamil)", async ({ page, api }) => {
    test.setTimeout(120_000);
    const callId = await startLabCall(page, { scenario: "unsupported-tamil", autoplay: true });
    await expect(page.getByTestId("lab-console")).toHaveAttribute("data-status", "ended", { timeout: 90_000 });
    const call = await api.getCall(callId);
    expect(call.turns.some((turn) => turn.speaker === "caller")).toBe(true);
    await expect(page.getByTestId("lab-summary")).toBeVisible({ timeout: 15_000 });
  });

  test("the sanitized diagnostic report downloads as JSON without the raw caller number", async ({ page, api }) => {
    const call = await api.seedCall("bank-otp-en");
    await page.goto(`/calls/${call.id}`);
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-report").click()]);
    expect(download.suggestedFilename()).toMatch(/\.json$/);
    const path = await download.path();
    const text = readFileSync(path, "utf8");
    const report = JSON.parse(text) as Record<string, unknown>;
    expect(Object.keys(report).length).toBeGreaterThan(3);
    expect(text).not.toContain("9800000101");
    expect(text).toContain(call.trace_id);
  });
});
