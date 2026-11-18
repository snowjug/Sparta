import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, formatDurationSpoken, formatMinutes, formatPercent, formatRelative, localDateToIso, truncate } from "./format";
import { categoryLabel, humanize, signalLabel, stateLabel, timelineDetail, timelineLabel } from "./labels";
import { htmlLang, languageChanges, languageName, languageShort, profileLabel, recognitionLocale, turnLanguage, variantLabel } from "./language";
import { riskMeterFill, riskVisual, severityTone } from "./risk";
import { describeCallState, STEPPER_STEPS } from "./call-state";
import { splitByExcerpts } from "./highlight";
import { safeRoute } from "./routes";
import { makeTurn } from "@/test/fixtures";

describe("format", () => {
  it("formats durations with tabular-friendly m:ss and a spoken form", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(65_000)).toBe("1:05");
    expect(formatDuration(3_725_000)).toBe("1:02:05");
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(-1)).toBe("—");
    expect(formatDurationSpoken(65_000)).toBe("1 minute 5 seconds");
    expect(formatDurationSpoken(1000)).toBe("1 second");
  });

  it("formats percentages, bytes, minutes and relative times defensively", () => {
    expect(formatPercent(0.876)).toBe("88%");
    expect(formatPercent(2)).toBe("100%");
    expect(formatPercent(undefined)).toBe("—");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(8_000_000)).toBe("7.6 MB");
    expect(formatMinutes(3.66)).toBe("3.7");
    expect(formatMinutes(42.4)).toBe("42");
    const now = Date.parse("2026-11-17T10:00:00Z");
    expect(formatRelative("2026-11-17T09:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-11-17T09:00:00Z", now, "en")).toMatch(/hour/);
    expect(formatRelative("nonsense", now)).toBe("—");
    expect(truncate("abcdefghij", 5)).toBe("abcd…");
  });

  it("converts date inputs to ISO instants at the day edges", () => {
    expect(localDateToIso("2026-11-17", "start")).toMatch(/^2026-11-1[67]T/);
    const start = Date.parse(localDateToIso("2026-11-17", "start")!);
    const end = Date.parse(localDateToIso("2026-11-17", "end")!);
    expect(end - start).toBeGreaterThan(86_000_000);
    expect(localDateToIso("17-11-2026", "start")).toBeUndefined();
  });
});

describe("labels", () => {
  it("uses plain language and falls back gracefully for values a newer server may send", () => {
    expect(categoryLabel("possible_financial_impersonation")).toBe("Possible bank or financial impersonation");
    expect(categoryLabel("brand_new_thing")).toBe("Brand new thing");
    expect(signalLabel("OTP_REQUEST")).toBe("Asked for a one-time code (OTP)");
    expect(stateLabel("ESCALATE")).toBe("Waiting for you");
    expect(stateLabel(null)).toBe("Waiting");
    expect(humanize("refused_and_ended")).toBe("Refused and ended");
  });

  it("rewrites machine-flavoured timeline entries", () => {
    expect(timelineLabel({ label: "State: IDENTIFY_CALLER" })).toBe("Step: Asking who is calling");
    expect(timelineLabel({ label: "Language: hi-IN (hinglish)" })).toBe("Language: Hindi (Hinglish)");
    expect(timelineLabel({ label: "Call started" })).toBe("Call started");
    expect(timelineDetail("continue_screening")).toBe("Keep screening");
    expect(timelineDetail(null)).toBe("");
  });
});

describe("language helpers", () => {
  it("names languages and variants, including Hinglish and Kanglish", () => {
    expect(languageName("hi-IN")).toBe("Hindi");
    expect(languageName("kn")).toBe("Kannada");
    expect(languageName("und")).toBe("Unknown language");
    expect(languageName("auto")).toBe("Auto-detect");
    expect(languageName("xx-YY")).toBe("xx-YY");
    expect(languageShort("kn-IN")).toBe("KN");
    expect(variantLabel("hinglish")).toBe("Hinglish");
    expect(variantLabel("kanglish")).toBe("Kanglish");
    expect(variantLabel("english")).toBeNull();
    expect(profileLabel("kanglish")).toBe("Kanglish");
    expect(profileLabel("hindi")).toBe("Hindi");
    expect(profileLabel("mixed")).toBe("Mixed");
  });

  it("derives per-turn language info and finds language switches between caller turns", () => {
    const turns = [
      makeTurn({ seq: 1, language: "en-IN", language_profile: "english" }),
      makeTurn({ seq: 2, speaker: "assistant", language: "en-IN", source: "assistant" }),
      makeTurn({ seq: 3, language: "hi-IN", language_profile: "hinglish" }),
      makeTurn({ seq: 4, speaker: "assistant", language: "hi-IN", source: "assistant" }),
      makeTurn({ seq: 5, language: "kn-IN", language_profile: "kanglish" }),
      makeTurn({ seq: 6, language: "kn-IN", language_profile: "kanglish" }),
    ];
    expect(languageChanges(turns)).toEqual([
      { beforeTurnId: "turn_3", from: "en-IN", to: "hi-IN", variant: "Hinglish" },
      { beforeTurnId: "turn_5", from: "hi-IN", to: "kn-IN", variant: "Kanglish" },
    ]);
    expect(turnLanguage(turns[2]!)).toMatchObject({ name: "Hindi", variant: "Hinglish" });
  });

  it("exposes safe `lang` attributes and microphone locales", () => {
    expect(htmlLang("hi-IN")).toBe("hi-IN");
    expect(htmlLang("und")).toBeUndefined();
    expect(htmlLang(null)).toBeUndefined();
    expect(recognitionLocale("kn-IN")).toBe("kn-IN");
    expect(recognitionLocale("auto", "en-GB")).toBe("en-GB");
    expect(recognitionLocale("auto", "")).toBe("en-IN");
  });
});

describe("risk and call-state visual mappings", () => {
  it("never fills the meter for 'unknown' and uses green only for low, red only for high", () => {
    expect(riskMeterFill("unknown", 0.9)).toBe(0);
    expect(riskMeterFill("low", 0.2)).toBeCloseTo(0.2);
    expect(riskMeterFill("high", undefined)).toBeGreaterThan(0.8);
    expect(riskVisual("low").tone).toBe("success");
    expect(riskVisual("medium").tone).toBe("warning");
    expect(riskVisual("high").tone).toBe("danger");
    expect(riskVisual("unknown").tone).toBe("neutral");
    expect(riskVisual("something-new").level).toBe("unknown");
    expect(riskVisual(null).level).toBe("unknown");
    expect(severityTone("critical", "legitimate")).toBe("success");
    expect(severityTone("medium")).toBe("warning");
  });

  it("maps call states to a step, an outcome label and who has to act", () => {
    expect(describeCallState("DISCLOSURE").step).toBe(1);
    expect(describeCallState("IDENTIFY_PURPOSE").step).toBe(3);
    const escalate = describeCallState("ESCALATE");
    expect(escalate).toMatchObject({ step: 5, needsOwner: true, tone: "warning", outcomeLabel: "Waiting for you" });
    const spam = describeCallState("END_SPAM");
    expect(spam).toMatchObject({ finished: true, outcomeLabel: "Ended: spam" });
    expect(describeCallState("COMPLETED", "ended").finished).toBe(true);
    expect(describeCallState(null).label).toBe("Waiting");
    expect(describeCallState("FAILED").tone).toBe("danger");
    expect(STEPPER_STEPS).toHaveLength(6);
  });
});

describe("splitByExcerpts (evidence highlighting)", () => {
  it("marks the excerpt ignoring case and punctuation differences", () => {
    const parts = splitByExcerpts("Hello, please share the OTP now.", ["please share the otp"]);
    expect(parts.map((p) => p.text).join("")).toBe("Hello, please share the OTP now.");
    expect(parts.find((p) => p.mark)?.text).toBe("please share the OTP");
  });

  it("merges overlaps, ignores tiny or missing excerpts, and works on non-Latin text", () => {
    const merged = splitByExcerpts("share the otp code today", ["share the otp", "otp code"]);
    expect(merged.filter((p) => p.mark)).toHaveLength(1);
    expect(splitByExcerpts("nothing here", ["xyz not found", "ab"])).toEqual([{ text: "nothing here", mark: false }]);
    const hindi = splitByExcerpts("मुझे अपना ओटीपी बताइए", ["अपना ओटीपी"]);
    expect(hindi.find((p) => p.mark)?.text).toBe("अपना ओटीपी");
    expect(splitByExcerpts("", ["abc"])).toEqual([]);
  });

  it("never produces HTML: returned segments are plain strings", () => {
    const parts = splitByExcerpts("<img src=x onerror=alert(1)> otp", ["otp"]);
    expect(parts.map((p) => p.text).join("")).toBe("<img src=x onerror=alert(1)> otp");
  });
});

describe("safeRoute", () => {
  it("only follows routes that belong to this app", () => {
    expect(safeRoute("/onboarding")).toBe("/onboarding");
    expect(safeRoute("/live/call_abc123")).toBe("/live/call_abc123");
    expect(safeRoute("/calls/call_1")).toBe("/calls/call_1");
    expect(safeRoute("/simulator")).toBe("/simulator");
    expect(safeRoute("/")).toBe("/");
    for (const bad of ["https://evil.example", "//evil.example", "/calls/../../etc", "javascript:alert(1)", "/unknown", "", null, undefined]) {
      expect(safeRoute(bad as string | null | undefined)).toBe("/");
    }
  });
});
