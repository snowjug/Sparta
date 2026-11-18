# ADR 0006 — Two-clock retention

* Status: accepted
* Date: 2026-11-18

## Context

The call transcript is the most sensitive thing Sparta handles: a recording-like record of a stranger's words and of what
the assistant said. The owner nevertheless needs a history that is useful (who called, what they wanted, how risky it was,
what Sparta did) long after the exact words stop mattering. The product brief asks for privacy by default, minimal and
configurable retention, deletion on request, and a record that stays useful. Different data has different value and risk,
so one retention period would either keep transcripts too long or throw the useful summary away too soon.

## Decision

Each owner has two retention clocks (`RetentionPolicy` in `domain/models.py`, enforced by
`services/retention.py` and `db/repository.py`):

1. **Transcript clock**, `transcript_retention_days`, default 7 (0 to 365), measured from the end of the call. When it
   expires the turns, the live-event log, the quotes in escalations and every evidence excerpt are deleted
   (`delete_transcript`). The summary, the caller's claimed name and organisation, the purpose, and the structured risk
   explanation (signal codes, reasons, scores, category, level, action taken) are kept because none of them quotes the
   caller.
2. **Record clock**, `summary_retention_days`, default 90 (1 to 730), measured from the start of the call. When it expires
   the whole call record is deleted.
3. **Owner-initiated deletion is stronger than expiry.** `DELETE /calls/{id}/content` and `DELETE /calls` also delete the
   summary, the risk rows, the claim and the purpose and the cached idempotent responses that belong to the call (the
   requests made against it and the response that created it), leaving a shell of timestamps, category, risk level and
   masked display. `DELETE /calls/{id}` deletes everything.
4. **An owner can store no transcripts at all** (`store_transcripts = false`): the transcript is deleted when the call is
   finalised.
5. **Raw audio is never stored**, so no clock applies to it.
6. **Storage is shaped for this.** Content-bearing and personal columns are encrypted; the fields needed to list, filter and
   cap calls (risk level, category, timestamps, flags, masked number, number fingerprint) are in clear, so a call can be
   listed and explained after its content is gone.
7. **A background job applies retention** inside the API process every hour (`SPARTA_RETENTION_JOB_INTERVAL_S`), in
   batches of 500 calls per owner and at most 20 batches (10,000 calls) per owner per run, and also purges expired
   idempotency records (15 minutes or 24 hours) and provider event ids after 30 days.

## Consequences

* Positive: verbatim speech is kept for days, not months, by default; the useful record survives; the owner can remove
  content at any time; deleting content never breaks the call list.
* Negative: the summary, claimed name and organisation, and purpose persist for 90 days by default, and a summary can
  contain a name the caller gave.
* Negative: retention runs only while an API process is running; nothing else enforces it, and the first run happens one
  interval after start.
* Negative: some data is outside both clocks: audit events are never purged; the encrypted cached response to a voice
  enrolment is kept for up to 24 hours and `DELETE /voice` does not remove it (the same holds for the response that
  creates a simulator scenario, which has no delete route); and the owner's display name, `caller_label` and
  classification fields are stored in clear and are not removed by "delete content". The copies that belong to a call
  are deleted with the call or its content: the response that created the call carries its `call_id` (migration `0002`),
  and the copies for requests that carry transcript text are kept 15 minutes. Removing a blocked or trusted entry
  deletes the cached `POST` responses of that list. There is no account-deletion operation
  ([PRIVACY.md](../PRIVACY.md) section 6).
* Negative: key rotation does not re-encrypt old rows, so an old key has to stay configured until its rows are gone.
* The defaults (7 and 90 days) are a product choice, not a legal conclusion; retention periods need legal review for each
  place of use.

## Alternatives considered

* **A single retention period for everything.** Rejected: either the summary disappears with the transcript or the
  transcript is kept as long as the summary.
* **Never store transcripts.** Available as the owner's setting, but not the default because the owner can review what was
  said while it matters.
* **Keep everything until the owner deletes it.** Rejected as a default: it contradicts minimal retention.
* **Database-level expiry (time-to-live, partition drops).** Not used: the rules (keep some columns, scrub others, skip
  active calls) are per-owner and per-row, and are easier to test in application code.
