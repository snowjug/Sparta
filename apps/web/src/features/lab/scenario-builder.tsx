"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { RECOMMENDED_ACTIONS } from "@/lib/api/enums";
import { newIdempotencyKey } from "@/lib/api/client";
import { fieldErrors } from "@/lib/api/errors";
import { useApi } from "@/lib/api/provider";
import type { CreateScenarioRequest, ScenarioSummary } from "@/lib/api/types";
import { ACTION_LABELS } from "@/lib/labels";
import { languageName } from "@/lib/language";
import { qk } from "@/lib/query/keys";
import { Button, IconButton } from "@/components/ui/button";
import { Checkbox, Field, Select, SegmentedControl, TextArea, TextInput } from "@/components/ui/form";
import { useToast } from "@/components/ui/toast";

const MAX_TURNS = 14;
const PROFILES = ["english", "hindi", "kannada", "hinglish", "kanglish", "mixed"];

interface DraftTurn {
  uid: number;
  kind: "speech" | "silence";
  text: string;
  language: string;
  delay: number;
  bargeIn: boolean;
}

let uidCounter = 0;
const blankTurn = (patch: Partial<DraftTurn> = {}): DraftTurn => ({ uid: (uidCounter += 1), kind: "speech", text: "", language: "auto", delay: 800, bargeIn: false, ...patch });

const EXAMPLE: Array<Partial<DraftTurn>> = [
  { text: "Hello, I'm calling from your bank about your account.", language: "en-IN" },
  { text: "Aapka KYC pending hai, jaldi update kijiye.", language: "hi-IN" },
  { text: "Please share the OTP you just received.", language: "en-IN" },
];

/** Custom scenario builder (POST /simulator/scenarios). Validated here for friendliness and again by the API. */
export function ScenarioBuilder({ onCreated }: { onCreated: (scenario: ScenarioSummary) => void }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [profile, setProfile] = useState("mixed");
  const [expected, setExpected] = useState("");
  const [turns, setTurns] = useState<DraftTurn[]>(() => [blankTurn()]);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const key = useRef(newIdempotencyKey());

  const speechMissing = turns.some((turn) => turn.kind === "speech" && turn.text.trim().length === 0);
  const titleMissing = title.trim().length === 0;
  const valid = !titleMissing && turns.length >= 1 && !speechMissing;

  const create = useMutation({
    mutationFn: () => {
      const body: CreateScenarioRequest = {
        title: title.trim(),
        description: description.trim(),
        language_profile: profile,
        expected_action: expected || undefined,
        turns: turns.map((turn) => ({
          kind: turn.kind,
          text: turn.kind === "speech" ? turn.text.trim() : "",
          language: turn.language === "auto" ? null : turn.language,
          delay_ms: Math.min(15000, Math.max(0, Math.round(turn.delay))),
          barge_in: turn.bargeIn,
        })),
      };
      return api.simulator.createScenario(body, { idempotencyKey: key.current });
    },
    onSuccess: (scenario) => {
      key.current = newIdempotencyKey();
      void queryClient.invalidateQueries({ queryKey: qk.scenarios });
      toast.success(`“${scenario.title}” was created. It is selected above.`, { title: "Scenario created" });
      setTitle("");
      setDescription("");
      setExpected("");
      setTurns([blankTurn()]);
      setServerErrors({});
      onCreated(scenario);
    },
    onError: (error) => setServerErrors(fieldErrors(error)),
  });

  const patch = (uid: number, change: Partial<DraftTurn>) => setTurns((list) => list.map((turn) => (turn.uid === uid ? { ...turn, ...change } : turn)));
  const move = (index: number, delta: -1 | 1) =>
    setTurns((list) => {
      const target = index + delta;
      if (target < 0 || target >= list.length) return list;
      const next = [...list];
      [next[index], next[target]] = [next[target]!, next[index]!];
      return next;
    });

  return (
    <form
      className="space-y-5"
      aria-label="Custom scenario builder"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) create.mutate();
      }}
      data-testid="scenario-builder"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Title" required error={serverErrors.title}>
          {(props) => <TextInput {...props} value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} data-testid="scenario-title" autoComplete="off" />}
        </Field>
        <Field label="Language profile">
          {(props) => (
            <Select {...props} value={profile} onChange={(event) => setProfile(event.target.value)}>
              {PROFILES.map((value) => (
                <option key={value} value={value}>
                  {value.charAt(0).toUpperCase() + value.slice(1)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Description (optional)" className="sm:col-span-2">
          {(props) => <TextArea {...props} rows={2} value={description} maxLength={300} onChange={(event) => setDescription(event.target.value)} />}
        </Field>
        <Field label="Expected outcome (optional)" hint="Used only to show whether the run matched what you expected.">
          {(props) => (
            <Select {...props} value={expected} onChange={(event) => setExpected(event.target.value)}>
              <option value="">No expectation</option>
              {RECOMMENDED_ACTIONS.map((action) => (
                <option key={action} value={action}>
                  {ACTION_LABELS[action]}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-fg">
          Caller turns ({turns.length}/{MAX_TURNS})
        </legend>
        <ol className="space-y-3">
          {turns.map((turn, index) => (
            <li key={turn.uid} className="space-y-3 rounded-2xl border border-line bg-raised p-4" data-testid="scenario-turn">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-fg">Turn {index + 1}</p>
                <div className="flex items-center">
                  <IconButton icon="chevron-up" label={`Move turn ${index + 1} up`} onClick={() => move(index, -1)} disabled={index === 0} />
                  <IconButton icon="chevron-down" label={`Move turn ${index + 1} down`} onClick={() => move(index, 1)} disabled={index === turns.length - 1} />
                  <IconButton icon="trash" label={`Remove turn ${index + 1}`} onClick={() => setTurns((list) => (list.length > 1 ? list.filter((t) => t.uid !== turn.uid) : list))} disabled={turns.length === 1} />
                </div>
              </div>
              <SegmentedControl
                legend={`What happens in turn ${index + 1}`}
                legendHidden
                value={turn.kind}
                onChange={(kind) => patch(turn.uid, { kind })}
                options={[
                  { value: "speech", label: "Caller speaks" },
                  { value: "silence", label: "Caller is silent" },
                ]}
                name={`turn-kind-${turn.uid}`}
              />
              {turn.kind === "speech" ? (
                <Field label="What the caller says" required error={serverErrors.text}>
                  {(props) => <TextArea {...props} rows={2} value={turn.text} maxLength={400} onChange={(event) => patch(turn.uid, { text: event.target.value })} data-testid="scenario-turn-text" />}
                </Field>
              ) : null}
              <div className="grid gap-3 sm:grid-cols-2">
                {turn.kind === "speech" ? (
                  <Field label="Language of this turn">
                    {(props) => (
                      <Select {...props} value={turn.language} onChange={(event) => patch(turn.uid, { language: event.target.value })}>
                        <option value="auto">{languageName("auto")}</option>
                        <option value="en-IN">{languageName("en-IN")}</option>
                        <option value="hi-IN">{languageName("hi-IN")}</option>
                        <option value="kn-IN">{languageName("kn-IN")}</option>
                      </Select>
                    )}
                  </Field>
                ) : null}
                <Field label={turn.kind === "silence" ? "Silence lasts (ms)" : "Wait before speaking (ms)"} hint="0 to 15000">
                  {(props) => (
                    <TextInput {...props} type="number" inputMode="numeric" min={0} max={15000} step={100} value={turn.delay} onChange={(event) => patch(turn.uid, { delay: Number(event.target.value) })} />
                  )}
                </Field>
              </div>
              {turn.kind === "speech" ? (
                <Checkbox checked={turn.bargeIn} onChange={(bargeIn) => patch(turn.uid, { bargeIn })} label="Speak over the assistant (barge-in)" description="Doesn't wait for the assistant to finish." />
              ) : null}
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" icon="plus" disabled={turns.length >= MAX_TURNS} onClick={() => setTurns((list) => [...list, blankTurn()])} data-testid="add-turn">
            Add turn
          </Button>
          <Button variant="secondary" onClick={() => setTurns(EXAMPLE.map((turn) => blankTurn(turn)))}>
            Fill with an example
          </Button>
        </div>
        {speechMissing ? <p className="text-sm font-medium text-danger">Every speaking turn needs some text.</p> : null}
      </fieldset>

      <Button type="submit" variant="primary" icon="check" disabled={!valid} loading={create.isPending} data-testid="create-scenario">
        Create scenario
      </Button>
    </form>
  );
}
