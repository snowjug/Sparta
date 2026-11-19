/**
 * GENERATED FILE: do not edit. Source: packages/contracts/openapi.json (owned by the API team).
 * Regenerate with `npm run types:api`. Hand-written helpers live in types.ts and enums.ts.
 */

export interface paths {
    "/api/v1/assistant-profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Profile */
        get: operations["account_get_profile"];
        /**
         * Put Profile
         * @description The AI disclosure is not part of the profile: it cannot be switched off. `use_personal_voice` is refused (409)
         *     unless the voice is `ready` and the feature is enabled.
         */
        put: operations["account_put_profile"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assistant-profile/preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Preview
         * @description Runs the real conversation engine on `sample_text` without creating a call or storing anything.
         */
        post: operations["account_preview"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/audit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Audit
         * @description Sensitive actions (deletions, exports, list changes, preference changes). Identifiers only, never content.
         */
        get: operations["safety_audit"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/blocked-callers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Blocked */
        get: operations["safety_list_blocked"];
        put?: never;
        /** Add Blocked */
        post: operations["safety_add_blocked"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/blocked-callers/{entry_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Blocked */
        delete: operations["safety_remove_blocked"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Calls */
        get: operations["calls_list_calls"];
        put?: never;
        /**
         * Create Call
         * @description Start a call through the configured telephony provider.
         *
         *     Real providers create calls when the provider delivers them, so this answers 409 `unsupported_by_provider` unless
         *     the provider is the simulator.
         */
        post: operations["calls_create_call"];
        /**
         * Delete All
         * @description Remove all of the owner's call content (calls stay as records without transcripts).
         */
        delete: operations["calls_delete_all"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Call */
        get: operations["calls_get_call"];
        put?: never;
        post?: never;
        /** Delete Call */
        delete: operations["calls_delete_call"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Audio
         * @description Transcribe an uploaded clip in memory and run it as a caller turn.
         *
         *     With the simulator STT there is no acoustic model: send `transcript_hint`, otherwise this is 422 `stt_unavailable`.
         */
        post: operations["calls_upload_audio"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/block": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Block */
        post: operations["calls_block"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Content
         * @description Remove the transcript, translations, live events, summary, risk explanation, claims and any feedback notes.
         *
         *     The call record stays (time, duration, status, final risk level and category, blocked/trusted flags).
         */
        delete: operations["calls_delete_content"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/continue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Owner action: continue
         * @description 409 `unsupported_by_provider` when the active telephony provider cannot do this; `CallDetail.capabilities` says which controls are real.
         */
        post: operations["calls_continue"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/end": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Owner action: end
         * @description 409 `unsupported_by_provider` when the active telephony provider cannot do this; `CallDetail.capabilities` says which controls are real.
         */
        post: operations["calls_end"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Events */
        get: operations["calls_events"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Call
         * @description Everything stored about one call (owner only). Includes the transcript while it is retained.
         */
        get: operations["calls_export_call"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/feedback": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Feedback
         * @description Idempotent per call and kind: repeating a kind updates the note of the existing record.
         */
        post: operations["calls_feedback"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/interrupt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Interrupt
         * @description Caller barge-in: stops the assistant's playback and keeps the conversation state.
         */
        post: operations["calls_interrupt"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/partial": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Partial
         * @description Emit a `transcript.partial` event only (no pipeline run): live captions while the caller is still speaking.
         */
        post: operations["calls_submit_partial"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Diagnostic Report
         * @description Sanitised diagnostic report: identifiers, states, timings and codes. No transcript text or numbers.
         */
        get: operations["calls_diagnostic_report"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/silence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Silence
         * @description Fire one silence timeout (what the timer does on a real call).
         */
        post: operations["calls_silence"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/takeover": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Owner action: takeover
         * @description 409 `unsupported_by_provider` when the active telephony provider cannot do this; `CallDetail.capabilities` says which controls are real.
         */
        post: operations["calls_takeover"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/trust": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Trust */
        post: operations["calls_trust"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}/turns": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Submit Turn */
        post: operations["calls_submit_turn"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/home": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Home
         * @description Protection status, the next useful action, today's counters and the calls that need the owner.
         */
        get: operations["system_home"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/live/ticket": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Live Ticket
         * @description A single-use WebSocket ticket for all of the owner's calls, or for one call (`call_id`).
         */
        post: operations["live_live_ticket"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["system_me"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/preferences": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Preferences */
        get: operations["account_get_preferences"];
        /**
         * Put Preferences
         * @description Replaces the owner's preferences. Unknown fields are rejected; languages and retention are validated.
         */
        put: operations["account_put_preferences"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/safety/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Safety Events
         * @description Medium and high risk calls with the signal codes that triggered them. Never transcript text.
         */
        get: operations["safety_safety_events"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/safety/policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Policies
         * @description What Sparta refuses and why, in the terms the policy itself uses (no hidden rules).
         */
        get: operations["safety_policies"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screening/config": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Config
         * @description `fingerprint_salt` is the base64 HMAC key the device uses to fingerprint numbers. Treat it as a secret.
         */
        get: operations["screening_config"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screening/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Event
         * @description Records what the device decided as a `screening_only` call. Idempotent on `client_event_id`: native screening
         *     cannot answer a call or hear its audio, so such a call has no transcript.
         */
        post: operations["screening_event"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/screening/lists": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Lists */
        get: operations["screening_lists"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulator/calls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Simulated Call
         * @description With `scenario_id` and `autoplay`, the scripted caller is played server-side with its gaps, and every step is
         *     streamed over the live socket.
         */
        post: operations["simulator_create_simulated_call"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulator/providers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Providers
         * @description Which adapters are active and which could be: a provider that is not configured says what is missing.
         */
        get: operations["simulator_providers"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulator/replay": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Replay
         * @description Deterministic replay in an isolated container (virtual clock, in-memory database): the same input yields the same
         *     `checksum`. Nothing is written to the owner's call history.
         */
        post: operations["simulator_replay"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/simulator/scenarios": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Scenarios */
        get: operations["simulator_scenarios"];
        put?: never;
        /** Create Scenario */
        post: operations["simulator_create_scenario"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/system/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * System Status
         * @description Public and free of personal data. Clients must show a "Development identity" banner when `dev_banner` is true,
         *     and must show whether telephony is real or simulated.
         */
        get: operations["system_system_status"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trusted-callers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Trusted */
        get: operations["safety_list_trusted"];
        put?: never;
        /** Add Trusted */
        post: operations["safety_add_trusted"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/trusted-callers/{entry_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Remove Trusted */
        delete: operations["safety_remove_trusted"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/voice": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Voice Delete */
        delete: operations["account_voice_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/voice/consent": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Voice Consent */
        get: operations["account_voice_consent"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/voice/enroll": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Voice Enroll
         * @description Records consent. The status becomes `pending_provider_approval`: the voice provider's approval cannot be
         *     completed inside Sparta.
         */
        post: operations["account_voice_enroll"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/voice/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Voice Status */
        get: operations["account_voice_status"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/voices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Voices */
        get: operations["account_voices"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Healthz
         * @description Liveness: the process is up. Never touches dependencies, so a database outage does not restart the service.
         */
        get: operations["health_healthz"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Metrics
         * @description Prometheus text. Off unless `SPARTA_EXPOSE_METRICS=true`; counters and timings only (no personal data), but still
         *     restrict the route to your monitoring network.
         */
        get: operations["health_metrics"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/readyz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Readyz
         * @description Readiness: the hard dependencies answer: the database (reachable, schema present, migrations at the version this
         *     code expects) and shared state. A new revision therefore takes no traffic until `python -m sparta migrate` has run.
         *     A degraded telephony provider is reported but does not make the service unready, because the owner can still use
         *     everything else.
         */
        get: operations["health_readyz"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AssistantProfile
         * @description How the assistant presents itself. The AI disclosure is not configurable away.
         */
        AssistantProfile: {
            /**
             * Owner Display Name
             * @default the owner
             */
            owner_display_name?: string;
            /** @default concise */
            response_style?: components["schemas"]["ResponseStyle"];
            /**
             * Speaking Rate
             * @default 1
             */
            speaking_rate?: number;
            /**
             * Use Personal Voice
             * @default false
             */
            use_personal_voice?: boolean;
            /**
             * Voice Ids
             * @description locale → predefined voice id; empty uses the catalog default
             */
            voice_ids?: {
                [key: string]: string;
            };
        };
        /** AuditEntry */
        AuditEntry: {
            /** Action */
            action: string;
            /**
             * At
             * Format: date-time
             */
            at: string;
            /** Detail */
            detail?: {
                [key: string]: unknown;
            } | null;
            /** Target Id */
            target_id?: string | null;
            /** Target Type */
            target_type: string;
        };
        /** BlockedCaller */
        BlockedCaller: {
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /** Id */
            id: string;
            /** Number Display */
            number_display: string;
            /** Reason */
            reason?: string | null;
            /** Source Call Id */
            source_call_id?: string | null;
        };
        /** BlockedFingerprint */
        BlockedFingerprint: {
            /** Fingerprint */
            fingerprint: string;
            /** Id */
            id: string;
            /** Number Display */
            number_display: string;
        };
        /** BlockRequest */
        BlockRequest: {
            /** Reason */
            reason?: string | null;
        };
        /** Body_calls_upload_audio */
        Body_calls_upload_audio: {
            /**
             * File
             * @description audio/wav, audio/ogg or audio/webm
             */
            file: string;
            /** Language Hint */
            language_hint?: string | null;
            /** Transcript Hint */
            transcript_hint?: string | null;
        };
        /**
         * CallCapabilities
         * @description Which owner controls are honest/available for this call's provider. Unsupported controls carry a reason.
         */
        CallCapabilities: {
            /** Audio Note */
            audio_note?: string | null;
            /**
             * Can Block
             * @default true
             */
            can_block?: boolean;
            /**
             * Can Continue
             * @default false
             */
            can_continue?: boolean;
            /**
             * Can End
             * @default false
             */
            can_end?: boolean;
            /**
             * Can Take Over
             * @default false
             */
            can_take_over?: boolean;
            /**
             * Simulated
             * @default false
             */
            simulated?: boolean;
            /** Takeover Note */
            takeover_note?: string | null;
            /**
             * Takeover Via
             * @description What Take Over does with this provider: nothing, a simulated bridge, a call to the owner's phone number, or a ring of a SIP extension on the local server (never a PSTN number).
             * @default phone_number
             * @enum {string}
             */
            takeover_via?: "none" | "simulated" | "phone_number" | "sip_extension";
            /**
             * Two Way Audio
             * @default false
             */
            two_way_audio?: boolean;
        };
        /**
         * CallCategory
         * @description Owner-facing classification of a call.
         * @enum {string}
         */
        CallCategory: "unknown" | "silent" | "possible_financial_impersonation" | "possible_government_impersonation" | "possible_courier_impersonation" | "possible_tech_support_scam" | "possible_prize_scam" | "possible_employer_impersonation" | "prompt_injection_attempt" | "telemarketing" | "harassment" | "legitimate_delivery" | "legitimate_appointment" | "legitimate_recruiter" | "legitimate_support_callback" | "legitimate_personal" | "legitimate_urgent";
        /** CallDetail */
        CallDetail: {
            /** Action Taken */
            action_taken?: string | null;
            /**
             * Assistant Speaking
             * @description The assistant is mid-utterance right now (see `speaking_turn_id`).
             * @default false
             */
            assistant_speaking?: boolean;
            /**
             * Blocked
             * @default false
             */
            blocked?: boolean;
            caller_claim?: components["schemas"]["CallerClaim"];
            /**
             * Caller Display
             * @description Masked number or label; never the raw number unless the owner opted in
             */
            caller_display: string;
            capabilities?: components["schemas"]["CallCapabilities"];
            /** @default unknown */
            category?: components["schemas"]["CallCategory"];
            /**
             * Confidence
             * @default 0
             */
            confidence?: number;
            /** Duration Ms */
            duration_ms?: number | null;
            /** Ended At */
            ended_at?: string | null;
            /** Escalations */
            escalations?: components["schemas"]["Escalation"][];
            /** Feedback */
            feedback?: components["schemas"]["FeedbackRecord"][];
            /**
             * Has Content
             * @default true
             */
            has_content?: boolean;
            /** Id */
            id: string;
            /**
             * Language Mode
             * @default auto
             */
            language_mode?: string;
            /** Language Profile */
            language_profile?: string | null;
            /** Languages */
            languages?: string[];
            /** Metrics */
            metrics?: {
                [key: string]: number;
            };
            /** @default conversational */
            mode?: components["schemas"]["CallMode"];
            /** Owner Actions */
            owner_actions?: components["schemas"]["OwnerAction"][];
            /**
             * Owner Attention Required
             * @default false
             */
            owner_attention_required?: boolean;
            provider: components["schemas"]["ProviderKind"];
            /** Provider Events */
            provider_events?: components["schemas"]["ProviderEventRecord"][];
            /** Purpose */
            purpose?: string | null;
            risk?: components["schemas"]["RiskAssessment"] | null;
            /** @default unknown */
            risk_level?: components["schemas"]["RiskLevel"];
            /**
             * Risk Score
             * @default 0
             */
            risk_score?: number;
            /** Simulated */
            simulated: boolean;
            /**
             * Speaking Turn Id
             * @description Turn being spoken while `assistant_speaking`; its `speech.est_duration_ms` is known.
             */
            speaking_turn_id?: string | null;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            state: components["schemas"]["CallState"];
            status: components["schemas"]["CallStatus"];
            summary?: components["schemas"]["CallSummary"] | null;
            /** Summary Text */
            summary_text?: string | null;
            /** Timeline */
            timeline?: components["schemas"]["TimelineEntry"][];
            /**
             * Trace Id
             * @default
             */
            trace_id?: string;
            /**
             * Trusted
             * @default false
             */
            trusted?: boolean;
            /** Turns */
            turns?: components["schemas"]["CallTurn"][];
            versions?: components["schemas"]["VersionInfo"];
        };
        /** CallerClaim */
        CallerClaim: {
            /** Name */
            name?: string | null;
            /** Organization */
            organization?: string | null;
            /** Role */
            role?: string | null;
        };
        /** CallListItem */
        CallListItem: {
            /** Action Taken */
            action_taken?: string | null;
            /**
             * Blocked
             * @default false
             */
            blocked?: boolean;
            caller_claim?: components["schemas"]["CallerClaim"];
            /**
             * Caller Display
             * @description Masked number or label; never the raw number unless the owner opted in
             */
            caller_display: string;
            /** @default unknown */
            category?: components["schemas"]["CallCategory"];
            /**
             * Confidence
             * @default 0
             */
            confidence?: number;
            /** Duration Ms */
            duration_ms?: number | null;
            /** Ended At */
            ended_at?: string | null;
            /**
             * Has Content
             * @default true
             */
            has_content?: boolean;
            /** Id */
            id: string;
            /** Language Profile */
            language_profile?: string | null;
            /** Languages */
            languages?: string[];
            /** @default conversational */
            mode?: components["schemas"]["CallMode"];
            /**
             * Owner Attention Required
             * @default false
             */
            owner_attention_required?: boolean;
            provider: components["schemas"]["ProviderKind"];
            /** Purpose */
            purpose?: string | null;
            /** @default unknown */
            risk_level?: components["schemas"]["RiskLevel"];
            /**
             * Risk Score
             * @default 0
             */
            risk_score?: number;
            /** Simulated */
            simulated: boolean;
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
            state: components["schemas"]["CallState"];
            status: components["schemas"]["CallStatus"];
            /** Summary Text */
            summary_text?: string | null;
            /**
             * Trusted
             * @default false
             */
            trusted?: boolean;
        };
        /**
         * CallMode
         * @enum {string}
         */
        CallMode: "conversational" | "screening_only";
        /** CallPage */
        CallPage: {
            /** Items */
            items: components["schemas"]["CallListItem"][];
            /** Next Cursor */
            next_cursor?: string | null;
        };
        /**
         * CallState
         * @description Explicit conversation states. Transitions are validated in ``sparta.orchestrator.state_machine``.
         * @enum {string}
         */
        CallState: "INITIALIZING" | "DISCLOSURE" | "IDENTIFY_CALLER" | "IDENTIFY_PURPOSE" | "CLARIFY" | "ASSESSING" | "SAFE_CONTINUE" | "ESCALATE" | "REFUSE_SENSITIVE_REQUEST" | "END_SPAM" | "END_SILENCE" | "OWNER_TAKEOVER" | "COMPLETED" | "FAILED";
        /**
         * CallStatus
         * @enum {string}
         */
        CallStatus: "active" | "ended" | "failed";
        /** CallSummary */
        CallSummary: {
            /** Action Taken */
            action_taken?: string | null;
            /** Call Id */
            call_id: string;
            /** @default unknown */
            category?: components["schemas"]["CallCategory"];
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /**
             * Generated By
             * @default rules-v1
             */
            generated_by?: string;
            /**
             * Owner Action Required
             * @default false
             */
            owner_action_required?: boolean;
            /** @default unknown */
            risk_level?: components["schemas"]["RiskLevel"];
            /**
             * Text
             * @description One-sentence factual summary
             */
            text: string;
        };
        /** CallTurn */
        CallTurn: {
            /** Call Id */
            call_id: string;
            /** Confidence */
            confidence?: number | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /**
             * Id
             * @description Stable per-call turn id, e.g. 'turn_7'
             */
            id: string;
            /**
             * Interrupted
             * @default false
             */
            interrupted?: boolean;
            /**
             * Is Final
             * @default true
             */
            is_final?: boolean;
            /** Language */
            language?: string | null;
            /** Language Confidence */
            language_confidence?: number | null;
            /** Language Profile */
            language_profile?: string | null;
            latency?: components["schemas"]["LatencyBreakdown"] | null;
            /** Segments */
            segments?: components["schemas"]["LanguageSegment"][];
            /** Seq */
            seq: number;
            /** @default typed */
            source?: components["schemas"]["TurnSource"];
            speaker: components["schemas"]["Speaker"];
            speech?: components["schemas"]["SpeechPlan"] | null;
            /** Spoken Fraction */
            spoken_fraction?: number | null;
            state_after?: components["schemas"]["CallState"] | null;
            /** Text */
            text: string;
            /** Translation */
            translation?: string | null;
            /** Transliteration */
            transliteration?: string | null;
        };
        /** CreateCallRequest */
        CreateCallRequest: {
            /**
             * Autoplay
             * @default false
             */
            autoplay?: boolean;
            /** Caller Label */
            caller_label?: string | null;
            /** Caller Number */
            caller_number?: string | null;
            /**
             * Language Mode
             * @default auto
             */
            language_mode?: string;
            /**
             * Network Profile
             * @default ideal
             * @enum {string}
             */
            network_profile?: "ideal" | "mobile_4g" | "congested";
            /** Scenario Id */
            scenario_id?: string | null;
            /**
             * Silence Timers
             * @default preferences
             * @enum {string}
             */
            silence_timers?: "preferences" | "off";
        };
        /** CreateScenarioRequest */
        CreateScenarioRequest: {
            /**
             * Description
             * @default
             */
            description?: string;
            /** Expected Action */
            expected_action?: string | null;
            /**
             * Language Profile
             * @default mixed
             */
            language_profile?: string;
            /** Title */
            title: string;
            /** Turns */
            turns: components["schemas"]["ScenarioTurn"][];
        };
        /** ErrorBody */
        ErrorBody: {
            /** Code */
            code: string;
            /** Details */
            details?: components["schemas"]["ErrorDetail"][] | null;
            /** Message */
            message: string;
            /** Trace Id */
            trace_id: string;
        };
        /** ErrorDetail */
        ErrorDetail: {
            /** Field */
            field: string;
            /** Message */
            message: string;
        };
        /** ErrorEnvelope */
        ErrorEnvelope: {
            error: components["schemas"]["ErrorBody"];
        };
        /** Escalation */
        Escalation: {
            /** Call Id */
            call_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /** Id */
            id: string;
            /** Important Lines */
            important_lines?: string[];
            /** Reason */
            reason: string;
            /** Resolved At */
            resolved_at?: string | null;
            /** @default requested */
            status?: components["schemas"]["EscalationStatus"];
        };
        /** EscalationRules */
        EscalationRules: {
            /**
             * Auto End High Risk
             * @default true
             */
            auto_end_high_risk?: boolean;
            /** Escalate Categories */
            escalate_categories?: components["schemas"]["CallCategory"][];
            /**
             * Escalate Uncertain Urgent
             * @description Stored only: the screening engine does not act on this yet. Escalation follows escalate_categories.
             * @default true
             */
            escalate_uncertain_urgent?: boolean;
            /**
             * Owner Response Timeout S
             * @default 30
             */
            owner_response_timeout_s?: number;
        };
        /**
         * EscalationStatus
         * @enum {string}
         */
        EscalationStatus: "requested" | "taken_over" | "continued" | "ended" | "expired";
        /** FeaturesView */
        FeaturesView: {
            /** Llm Summaries */
            llm_summaries: boolean;
            /** Personal Voice */
            personal_voice: boolean;
            /**
             * Raw Audio Storage
             * @default false
             * @constant
             */
            raw_audio_storage?: false;
            /** Simulator */
            simulator: boolean;
            /** Translation */
            translation: boolean;
        };
        /**
         * FeedbackKind
         * @enum {string}
         */
        FeedbackKind: "correct_classification" | "was_spam" | "was_legitimate" | "wrong_language" | "poor_transcription" | "wrong_summary" | "trust_caller" | "block_caller";
        /** FeedbackRecord */
        FeedbackRecord: {
            /** Call Id */
            call_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /** Id */
            id: string;
            kind: components["schemas"]["FeedbackKind"];
            /** Note */
            note?: string | null;
        };
        /** FeedbackRequest */
        FeedbackRequest: {
            kind: components["schemas"]["FeedbackKind"];
            /** Note */
            note?: string | null;
        };
        /** HomeSummary */
        HomeSummary: {
            /** Attention */
            attention?: components["schemas"]["CallListItem"][];
            next_action: components["schemas"]["NextAction"];
            protection: components["schemas"]["ProtectionView"];
            /** Recent */
            recent?: components["schemas"]["CallListItem"][];
            today: components["schemas"]["TodayView"];
        };
        /** InterruptRequest */
        InterruptRequest: {
            /** Spoken Fraction */
            spoken_fraction?: number | null;
            /** Turn Id */
            turn_id?: string | null;
        };
        /** InterruptResult */
        InterruptResult: {
            /** Interrupted */
            interrupted: boolean;
            /** Interruption Ms */
            interruption_ms?: number | null;
            /** Spoken Fraction */
            spoken_fraction?: number | null;
            /** Turn Id */
            turn_id?: string | null;
        };
        /** LanguageSegment */
        LanguageSegment: {
            /** Confidence */
            confidence: number;
            /**
             * End
             * @description Character offset (exclusive) in the turn text
             */
            end: number;
            /**
             * Language
             * @description BCP-47 tag such as en-IN, hi-IN, kn-IN, or 'und'
             */
            language: string;
            /**
             * Romanized
             * @default false
             */
            romanized?: boolean;
            /**
             * Script
             * @enum {string}
             */
            script: "Latn" | "Deva" | "Knda" | "Mixed" | "Other";
            /**
             * Start
             * @description Character offset (inclusive) in the turn text
             */
            start: number;
            /** Variant */
            variant?: ("hinglish" | "kanglish") | null;
        };
        /** LanguageView */
        LanguageView: {
            /** Code */
            code: string;
            /** Name */
            name: string;
            /** Native Name */
            native_name: string;
            /**
             * Status
             * @enum {string}
             */
            status: "supported" | "planned";
        };
        /**
         * LatencyBreakdown
         * @description Per-stage timings in milliseconds for one caller turn → assistant response.
         *
         *     ``simulated_stages`` lists stages whose value came from a simulated provider profile rather than a measurement.
         */
        LatencyBreakdown: {
            /** Audio Input Ms */
            audio_input_ms?: number | null;
            /** Interruption Ms */
            interruption_ms?: number | null;
            /** Language Detect Ms */
            language_detect_ms?: number | null;
            /** Model Ms */
            model_ms?: number | null;
            /** Playback Start Ms */
            playback_start_ms?: number | null;
            /** Policy Ms */
            policy_ms?: number | null;
            /** Simulated Stages */
            simulated_stages?: string[];
            /** Stt Ms */
            stt_ms?: number | null;
            /** Total Ms */
            total_ms?: number | null;
            /** Tts First Audio Ms */
            tts_first_audio_ms?: number | null;
            /** Vad Ms */
            vad_ms?: number | null;
        };
        /** LimitsView */
        LimitsView: {
            /** Daily Call Cap */
            daily_call_cap: number;
            /** Max Audio Bytes */
            max_audio_bytes: number;
            /** Max Audio Seconds */
            max_audio_seconds: number;
            /** Max Call Duration S */
            max_call_duration_s: number;
        };
        /** ListNumberRequest */
        ListNumberRequest: {
            /** Label */
            label?: string | null;
            /** Number */
            number: string;
            /** Reason */
            reason?: string | null;
        };
        /**
         * LiveEvent
         * @description Envelope for every WebSocket message. ``seq`` is monotonic per call.
         */
        LiveEvent: {
            /** Call Id */
            call_id: string;
            /** Data */
            data?: {
                [key: string]: unknown;
            };
            /**
             * Seq
             * @default 0
             */
            seq?: number;
            /**
             * Simulated
             * @default false
             */
            simulated?: boolean;
            /**
             * Ts
             * Format: date-time
             */
            ts?: string;
            /** Type */
            type: string;
        };
        /** MeView */
        MeView: {
            /**
             * Auth Mode
             * @enum {string}
             */
            auth_mode: "dev" | "oidc";
            /** Display Name */
            display_name: string;
            /** Id */
            id: string;
        };
        /** NextAction */
        NextAction: {
            /**
             * Kind
             * @enum {string}
             */
            kind: "finish_onboarding" | "review_escalation" | "review_call" | "run_simulator" | "none";
            /** Label */
            label: string;
            /** Route */
            route: string;
        };
        /** NotificationPreferences */
        NotificationPreferences: {
            /**
             * Include Transcript Lines
             * @default true
             */
            include_transcript_lines?: boolean;
            /**
             * Notify On Escalation
             * @default true
             */
            notify_on_escalation?: boolean;
            /**
             * Notify On High Risk
             * @description Applied by the Android app to its own notifications. The server sends no push for it yet.
             * @default false
             */
            notify_on_high_risk?: boolean;
            /**
             * Quiet Hours End
             * @description Applied by the Android app to its own notifications. The server sends no push yet.
             */
            quiet_hours_end?: string | null;
            /**
             * Quiet Hours Start
             * @description Applied by the Android app to its own notifications. The server sends no push yet.
             */
            quiet_hours_start?: string | null;
        };
        /** OwnerAction */
        OwnerAction: {
            action: components["schemas"]["OwnerActionType"];
            /** Call Id */
            call_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /** Detail */
            detail?: string | null;
            /** Id */
            id: string;
            /**
             * Result
             * @default ok
             */
            result?: string;
            /**
             * Simulated
             * @default false
             */
            simulated?: boolean;
        };
        /** OwnerActionResult */
        OwnerActionResult: {
            action: components["schemas"]["OwnerAction"];
            call: components["schemas"]["CallListItem"];
            capabilities: components["schemas"]["CallCapabilities"];
        };
        /**
         * OwnerActionType
         * @enum {string}
         */
        OwnerActionType: "takeover" | "continue" | "end" | "block" | "trust" | "unblock" | "untrust";
        /** PartialRequest */
        PartialRequest: {
            /** Language Hint */
            language_hint?: string | null;
            /** Text */
            text: string;
        };
        /** PreviewRequest */
        PreviewRequest: {
            /**
             * Language
             * @default auto
             */
            language?: string;
            /** Sample Text */
            sample_text?: string | null;
        };
        /** PreviewResult */
        PreviewResult: {
            /** Detected Language */
            detected_language?: string | null;
            disclosure: components["schemas"]["SpeechPlan"];
            reply?: components["schemas"]["SpeechPlan"] | null;
            risk?: components["schemas"]["RiskAssessment"] | null;
        };
        /** PromptInjectionView */
        PromptInjectionView: {
            /** Examples */
            examples: string[];
            /** Summary */
            summary: string;
        };
        /** ProtectedInfoView */
        ProtectedInfoView: {
            /** Code */
            code: string;
            /** Label */
            label: string;
        };
        /** ProtectionView */
        ProtectionView: {
            /**
             * Connection
             * @default pstn
             * @enum {string}
             */
            connection?: "simulated" | "local_sip" | "pstn";
            /** Detail */
            detail: string;
            /** Headline */
            headline: string;
            /** Live Calls Supported */
            live_calls_supported: boolean;
            /** Provider */
            provider: string;
            /**
             * Pstn
             * @default provider
             * @enum {string}
             */
            pstn?: "not_applicable" | "not_configured" | "provider";
            /** Simulated */
            simulated: boolean;
            /**
             * Status
             * @enum {string}
             */
            status: "active" | "attention" | "degraded" | "setup_needed";
        };
        /**
         * ProviderEventRecord
         * @description Sanitized view of an inbound/outbound provider event (no payload bodies, no secrets).
         */
        ProviderEventRecord: {
            /** Detail */
            detail?: string | null;
            /** Event Type */
            event_type: string;
            /** External Id */
            external_id?: string | null;
            /** Id */
            id: string;
            /** Provider */
            provider: string;
            /**
             * Received At
             * Format: date-time
             */
            received_at?: string;
        };
        /**
         * ProviderKind
         * @enum {string}
         */
        ProviderKind: "simulator" | "azure" | "android_screening" | "asterisk" | "other";
        /** ProviderOption */
        ProviderOption: {
            /** Active */
            active: boolean;
            /** Available */
            available: boolean;
            /** Id */
            id: string;
            /**
             * Kind
             * @enum {string}
             */
            kind: "telephony" | "stt" | "tts" | "llm";
            /** Label */
            label: string;
            /**
             * Reason
             * @default
             */
            reason?: string;
            /** Simulated */
            simulated: boolean;
        };
        /**
         * RecommendedAction
         * @enum {string}
         */
        RecommendedAction: "continue_screening" | "ask_clarifying_question" | "escalate_to_owner" | "refuse_and_end" | "end_spam" | "block_recommended" | "report_recommended" | "human_review";
        /** ReplayRequest */
        ReplayRequest: {
            /**
             * Language Mode
             * @default auto
             */
            language_mode?: string;
            /**
             * Network Profile
             * @default ideal
             * @enum {string}
             */
            network_profile?: "ideal" | "mobile_4g" | "congested";
            /** Scenario Id */
            scenario_id: string;
        };
        /** ReplayResult */
        ReplayResult: {
            call: components["schemas"]["CallDetail"];
            /** Checksum */
            checksum: string;
            /** Checksum Covers */
            checksum_covers: string;
            /** Events */
            events: components["schemas"]["LiveEvent"][];
        };
        /**
         * ResponseStyle
         * @enum {string}
         */
        ResponseStyle: "concise" | "warm" | "formal";
        /**
         * RetentionPolicy
         * @description Privacy defaults: minimal retention, no raw audio.
         */
        RetentionPolicy: {
            /**
             * Store Full Caller Number
             * @default false
             */
            store_full_caller_number?: boolean;
            /**
             * Store Raw Audio
             * @default false
             */
            store_raw_audio?: boolean;
            /**
             * Store Transcripts
             * @default true
             */
            store_transcripts?: boolean;
            /**
             * Summary Retention Days
             * @default 90
             */
            summary_retention_days?: number;
            /**
             * Transcript Retention Days
             * @default 7
             */
            transcript_retention_days?: number;
        };
        /** RiskAssessment */
        RiskAssessment: {
            /**
             * Additional Actions
             * @description Extra advice alongside the primary action, e.g. block/report recommended
             */
            additional_actions?: components["schemas"]["RecommendedAction"][];
            /**
             * Assessed At
             * Format: date-time
             */
            assessed_at?: string;
            /** Call Id */
            call_id: string;
            caller_claim?: components["schemas"]["CallerClaim"];
            /** @default unknown */
            category?: components["schemas"]["CallCategory"];
            /**
             * Confidence
             * @default 0
             */
            confidence?: number;
            /** Detected Languages */
            detected_languages?: string[];
            /**
             * Language Profile
             * @description e.g. 'english', 'hinglish', 'kanglish'
             */
            language_profile?: string | null;
            /**
             * Policy Version
             * @default
             */
            policy_version?: string;
            /** Purpose */
            purpose?: string | null;
            /**
             * Reasons
             * @description Short evidence-based reasons. Never contains model reasoning.
             */
            reasons?: string[];
            /** @default continue_screening */
            recommended_action?: components["schemas"]["RecommendedAction"];
            /**
             * Requires Owner Attention
             * @default false
             */
            requires_owner_attention?: boolean;
            /** @default unknown */
            risk_level?: components["schemas"]["RiskLevel"];
            /**
             * Risk Score
             * @default 0
             */
            risk_score?: number;
            /** Signals */
            signals?: components["schemas"]["RiskSignal"][];
            /**
             * Turn Count
             * @default 0
             */
            turn_count?: number;
        };
        /**
         * RiskLevel
         * @description ``unknown`` means there is not enough evidence yet. Sparta never shows certainty it does not have.
         * @enum {string}
         */
        RiskLevel: "unknown" | "low" | "medium" | "high";
        /** RiskSignal */
        RiskSignal: {
            code: components["schemas"]["SignalCode"];
            /**
             * Description
             * @default
             */
            description?: string;
            /** Evidence Excerpt */
            evidence_excerpt?: string | null;
            /** Evidence Turn Ids */
            evidence_turn_ids?: string[];
            /** @default risk */
            kind?: components["schemas"]["SignalKind"];
            severity: components["schemas"]["SignalSeverity"];
            /**
             * Weight
             * @default 0
             */
            weight?: number;
        };
        /** SafetyEventView */
        SafetyEventView: {
            action?: components["schemas"]["RecommendedAction"] | null;
            /**
             * At
             * Format: date-time
             */
            at: string;
            /** Call Id */
            call_id: string;
            category: components["schemas"]["CallCategory"];
            risk_level: components["schemas"]["RiskLevel"];
            /** Signal Codes */
            signal_codes?: string[];
        };
        /** SafetyPolicyView */
        SafetyPolicyView: {
            /** Limits */
            limits: {
                [key: string]: number;
            };
            /** Name */
            name: string;
            prompt_injection: components["schemas"]["PromptInjectionView"];
            /** Protected Information */
            protected_information: components["schemas"]["ProtectedInfoView"][];
            /** Signals */
            signals: components["schemas"]["SignalView"][];
            strictness: components["schemas"]["ScreeningStrictness"];
            /** Thresholds */
            thresholds: {
                [key: string]: {
                    [key: string]: number;
                };
            };
            /** Version */
            version: string;
        };
        /** ScenarioSummary */
        ScenarioSummary: {
            /**
             * Custom
             * @default false
             */
            custom?: boolean;
            /**
             * Description
             * @default
             */
            description?: string;
            /** Expected Action */
            expected_action?: string | null;
            /** Id */
            id: string;
            /** Language Profile */
            language_profile: string;
            /** Languages */
            languages?: string[];
            /** Tags */
            tags?: string[];
            /** Title */
            title: string;
            /** Turn Count */
            turn_count: number;
        };
        /**
         * ScenarioTurn
         * @description One scripted caller step: a spoken turn, or silence (the caller says nothing for ``delay_ms``).
         */
        ScenarioTurn: {
            /**
             * Barge In
             * @description Speak over the assistant instead of waiting for it to finish
             * @default false
             */
            barge_in?: boolean;
            /**
             * Delay Ms
             * @default 800
             */
            delay_ms?: number;
            /**
             * Kind
             * @default speech
             * @enum {string}
             */
            kind?: "speech" | "silence";
            /** Language */
            language?: string | null;
            /** Stt Confidence */
            stt_confidence?: number | null;
            /**
             * Text
             * @default
             */
            text?: string;
        };
        /** ScreeningConfig */
        ScreeningConfig: {
            /** Fingerprint Salt */
            fingerprint_salt: string;
            /** Forwarding Number */
            forwarding_number?: string | null;
            /** Live Calls Supported */
            live_calls_supported: boolean;
            /** Provider */
            provider: string;
            strictness: components["schemas"]["ScreeningStrictness"];
            /**
             * Trusted Contact Behavior
             * @enum {string}
             */
            trusted_contact_behavior: "allow_directly" | "screen_anyway";
            /**
             * Unknown Caller Behavior
             * @enum {string}
             */
            unknown_caller_behavior: "screen" | "silence" | "allow";
        };
        /** ScreeningEventRequest */
        ScreeningEventRequest: {
            /** Client Event Id */
            client_event_id: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "allow" | "silence" | "reject";
            /** Direction */
            direction?: ("incoming" | "outgoing") | null;
            /**
             * Number Display
             * @default Private number
             */
            number_display?: string;
            /** Number Fingerprint */
            number_fingerprint: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /**
             * Reason
             * @default
             */
            reason?: string;
            /** Verification Status */
            verification_status?: string | null;
        };
        /** ScreeningLists */
        ScreeningLists: {
            /** Blocked */
            blocked: components["schemas"]["BlockedFingerprint"][];
            /** Trusted */
            trusted: components["schemas"]["TrustedFingerprint"][];
        };
        /**
         * ScreeningStrictness
         * @enum {string}
         */
        ScreeningStrictness: "relaxed" | "balanced" | "strict";
        /**
         * SignalCode
         * @description Risk and legitimacy signal identifiers (stable, versioned with the safety policy).
         * @enum {string}
         */
        SignalCode: "OTP_REQUEST" | "PASSWORD_REQUEST" | "PIN_REQUEST" | "CVV_REQUEST" | "CARD_OR_ACCOUNT_CREDENTIAL_REQUEST" | "AUTH_OR_RECOVERY_CODE_REQUEST" | "IDENTITY_DOCUMENT_REQUEST" | "ADDRESS_OR_LOCATION_REQUEST" | "OWNER_AVAILABILITY_PROBE" | "REMOTE_ACCESS_REQUEST" | "SCREEN_SHARING_REQUEST" | "PAYMENT_OR_TRANSFER_REQUEST" | "GIFT_CARD_OR_CRYPTO_REQUEST" | "MALICIOUS_LINK_OR_CALLBACK" | "ARREST_OR_LEGAL_THREAT" | "ACCOUNT_CLOSURE_THREAT" | "FAKE_KYC_URGENCY" | "URGENCY_PRESSURE" | "SUSPICIOUS_PRIZE" | "IMPERSONATION_BANK" | "IMPERSONATION_GOVERNMENT" | "IMPERSONATION_POLICE" | "IMPERSONATION_COURIER" | "IMPERSONATION_EMPLOYER" | "RULE_OVERRIDE_ATTEMPT" | "FALSE_OWNER_AUTHORIZATION" | "HARASSMENT_OR_ABUSE" | "TELEMARKETING" | "LEGIT_DELIVERY_COORDINATION" | "LEGIT_APPOINTMENT_CONFIRMATION" | "LEGIT_RECRUITER_INTRO" | "LEGIT_KNOWN_SERVICE_CALLBACK" | "LEGIT_FAMILY_OR_FRIEND" | "LEGIT_SCHOOL_OR_HOSPITAL" | "LEGIT_EMERGENCY_CONTEXT" | "LEGIT_SUPPORT_CALLBACK";
        /**
         * SignalKind
         * @enum {string}
         */
        SignalKind: "risk" | "legitimate";
        /**
         * SignalSeverity
         * @enum {string}
         */
        SignalSeverity: "info" | "low" | "medium" | "high" | "critical";
        /** SignalView */
        SignalView: {
            /** Code */
            code: string;
            /** Description */
            description: string;
            kind: components["schemas"]["SignalKind"];
            /** Protected */
            protected: boolean;
            severity: components["schemas"]["SignalSeverity"];
        };
        /**
         * Speaker
         * @enum {string}
         */
        Speaker: "caller" | "assistant" | "owner" | "system";
        /**
         * SpeechPlan
         * @description What the assistant will say. ``text`` is in the script the speech provider needs.
         */
        SpeechPlan: {
            /**
             * Est Duration Ms
             * @default 0
             */
            est_duration_ms?: number;
            /** Locale */
            locale: string;
            /**
             * Rate
             * @default 1
             */
            rate?: number;
            /** Ssml */
            ssml?: string | null;
            /** Style */
            style?: string | null;
            /** Text */
            text: string;
            /**
             * Transliteration
             * @description Latin-script rendering for developers/testers when text is in a native script
             */
            transliteration?: string | null;
            /** Voice Id */
            voice_id?: string | null;
        };
        /** SystemStatus */
        SystemStatus: {
            /**
             * Auth Mode
             * @enum {string}
             */
            auth_mode: "dev" | "oidc";
            /** Dev Banner */
            dev_banner: boolean;
            /** Env */
            env: string;
            features: components["schemas"]["FeaturesView"];
            /** Language Pack Version */
            language_pack_version: string;
            /** Languages */
            languages: components["schemas"]["LanguageView"][];
            limits: components["schemas"]["LimitsView"];
            /** Llm Model */
            llm_model?: string | null;
            /** Llm Provider */
            llm_provider: string;
            /** Policy Version */
            policy_version: string;
            /** Stt Provider */
            stt_provider: string;
            telephony: components["schemas"]["TelephonyView"];
            /** Tts Provider */
            tts_provider: string;
            /** Version */
            version: string;
        };
        /** TelephonyView */
        TelephonyView: {
            /**
             * Connection
             * @description How calls reach Sparta with this provider: simulated typing, local SIP over IP (no phone number), or a phone-network provider.
             * @default pstn
             * @enum {string}
             */
            connection?: "simulated" | "local_sip" | "pstn";
            /** Forwarding Number */
            forwarding_number?: string | null;
            /** Live Calls Supported */
            live_calls_supported: boolean;
            /**
             * Note
             * @default
             */
            note?: string;
            /**
             * Provider
             * @enum {string}
             */
            provider: "simulator" | "azure" | "asterisk" | "other";
            /**
             * Pstn
             * @description Whether ordinary mobile and landline numbers can reach Sparta: never with the simulator, not configured with local SIP (that needs a carrier, a number and a trunk), else through the provider.
             * @default provider
             * @enum {string}
             */
            pstn?: "not_applicable" | "not_configured" | "provider";
            /** Simulated */
            simulated: boolean;
            /**
             * Takeover
             * @description What Take Over does with this provider.
             * @default phone_number
             * @enum {string}
             */
            takeover?: "none" | "simulated" | "phone_number" | "sip_extension";
        };
        /** TicketRequest */
        TicketRequest: {
            /** Call Id */
            call_id?: string | null;
        };
        /** TicketResponse */
        TicketResponse: {
            /** Expires In */
            expires_in: number;
            /** Ticket */
            ticket: string;
            /**
             * Ws Url
             * @description Complete WebSocket URL including the ticket; clients may also build it themselves
             */
            ws_url: string;
        };
        /** TimelineEntry */
        TimelineEntry: {
            /**
             * At
             * Format: date-time
             */
            at: string;
            /** Detail */
            detail?: string | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "state" | "owner_action" | "escalation" | "risk" | "language" | "provider" | "system";
            /** Label */
            label: string;
        };
        /** TodayView */
        TodayView: {
            /**
             * Ended Spam
             * @default 0
             */
            ended_spam?: number;
            /**
             * Escalations
             * @default 0
             */
            escalations?: number;
            /**
             * Handled
             * @default 0
             */
            handled?: number;
            /**
             * High Risk
             * @default 0
             */
            high_risk?: number;
            /**
             * Minutes Handled
             * @default 0
             */
            minutes_handled?: number;
        };
        /** TrustedCaller */
        TrustedCaller: {
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /** Id */
            id: string;
            /** Label */
            label?: string | null;
            /** Number Display */
            number_display: string;
            /** Source Call Id */
            source_call_id?: string | null;
        };
        /** TrustedFingerprint */
        TrustedFingerprint: {
            /** Fingerprint */
            fingerprint: string;
            /** Id */
            id: string;
            /** Label */
            label?: string | null;
            /** Number Display */
            number_display: string;
        };
        /** TrustRequest */
        TrustRequest: {
            /** Label */
            label?: string | null;
        };
        /** TurnRequest */
        TurnRequest: {
            /** Client Turn Id */
            client_turn_id?: string | null;
            /** Language Hint */
            language_hint?: string | null;
            /**
             * Source
             * @default typed
             * @enum {string}
             */
            source?: "typed" | "browser_stt" | "scripted";
            /** Stt Confidence */
            stt_confidence?: number | null;
            /** Text */
            text: string;
        };
        /** TurnResult */
        TurnResult: {
            assistant_turn: components["schemas"]["CallTurn"] | null;
            call: components["schemas"]["CallListItem"];
            caller_turn: components["schemas"]["CallTurn"] | null;
            /** Ended */
            ended: boolean;
            escalation?: components["schemas"]["Escalation"] | null;
            /** Interrupted Turn Id */
            interrupted_turn_id?: string | null;
            risk: components["schemas"]["RiskAssessment"] | null;
            state: components["schemas"]["CallState"];
        };
        /**
         * TurnSource
         * @enum {string}
         */
        TurnSource: "typed" | "browser_stt" | "provider_stt" | "uploaded_audio" | "scripted" | "assistant" | "system";
        /** UserPreferences */
        UserPreferences: {
            /**
             * Auto Detect Language
             * @default true
             */
            auto_detect_language?: boolean;
            /** Enabled Languages */
            enabled_languages?: string[];
            escalation?: components["schemas"]["EscalationRules"];
            /**
             * Max Call Duration S
             * @default 180
             */
            max_call_duration_s?: number;
            notifications?: components["schemas"]["NotificationPreferences"];
            /**
             * Onboarding Completed
             * @default false
             */
            onboarding_completed?: boolean;
            /**
             * Primary Language
             * @default en-IN
             */
            primary_language?: string;
            retention?: components["schemas"]["RetentionPolicy"];
            /**
             * Silence First Timeout S
             * @default 8
             */
            silence_first_timeout_s?: number;
            /**
             * Silence Second Timeout S
             * @default 8
             */
            silence_second_timeout_s?: number;
            /** @default balanced */
            strictness?: components["schemas"]["ScreeningStrictness"];
            /**
             * Takeover Number
             * @description Where a real provider bridges the call when you tap Take Over (never used by the simulator)
             */
            takeover_number?: string | null;
            /**
             * Translate Transcripts To
             * @description Stored for a future translation provider; no provider translates caller speech yet (`/system/status` features.translation is false). Assistant lines always carry an English rendering.
             * @default en-IN
             */
            translate_transcripts_to?: string | null;
            /**
             * Trusted Contact Behavior
             * @default allow_directly
             * @enum {string}
             */
            trusted_contact_behavior?: "allow_directly" | "screen_anyway";
            /**
             * Unknown Caller Behavior
             * @default screen
             * @enum {string}
             */
            unknown_caller_behavior?: "screen" | "silence" | "allow";
        };
        /** VersionInfo */
        VersionInfo: {
            /**
             * App Version
             * @default
             */
            app_version?: string;
            /**
             * Language Pack Version
             * @default
             */
            language_pack_version?: string;
            /** Llm Model */
            llm_model?: string | null;
            /**
             * Llm Provider
             * @default
             */
            llm_provider?: string;
            /**
             * Policy Version
             * @default
             */
            policy_version?: string;
            /**
             * Stt Provider
             * @default
             */
            stt_provider?: string;
            /**
             * Telephony Provider
             * @default
             */
            telephony_provider?: string;
            /**
             * Tts Provider
             * @default
             */
            tts_provider?: string;
        };
        /** VoiceConsentView */
        VoiceConsentView: {
            /**
             * Requires Provider Approval
             * @default true
             */
            requires_provider_approval?: boolean;
            /** Supported Locales */
            supported_locales?: string[];
            /** Text */
            text: string;
            /** Version */
            version: string;
        };
        /** VoiceEnrollRequest */
        VoiceEnrollRequest: {
            /** Consent */
            consent: boolean;
            /** Consent Version */
            consent_version: string;
            /** Speaker Name */
            speaker_name: string;
        };
        /** VoiceOption */
        VoiceOption: {
            /** Display Name */
            display_name: string;
            /**
             * Gender
             * @enum {string}
             */
            gender: "female" | "male" | "neutral";
            /** Id */
            id: string;
            /** Locale */
            locale: string;
            /** Note */
            note?: string | null;
            /** Provider */
            provider: string;
            /**
             * Verified
             * @description True only if the voice name was verified in provider documentation
             */
            verified: boolean;
        };
        /** VoiceProfileView */
        VoiceProfileView: {
            /**
             * Active
             * @default false
             */
            active?: boolean;
            /** Consent Recorded At */
            consent_recorded_at?: string | null;
            /** Consent Version */
            consent_version?: string | null;
            /**
             * Detail
             * @default No personal voice enrolled. A predefined natural voice is used.
             */
            detail?: string;
            /** Provider Voice Id */
            provider_voice_id?: string | null;
            /**
             * Requires Provider Approval
             * @default true
             */
            requires_provider_approval?: boolean;
            /** @default not_enrolled */
            status?: components["schemas"]["VoiceStatus"];
        };
        /**
         * VoiceStatus
         * @enum {string}
         */
        VoiceStatus: "not_enrolled" | "consent_recorded" | "pending_provider_approval" | "ready" | "failed" | "deleted";
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    account_get_profile: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssistantProfile"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_put_profile: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssistantProfile"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssistantProfile"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_preview: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PreviewResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_audit: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuditEntry"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_list_blocked: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BlockedCaller"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_add_blocked: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ListNumberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BlockedCaller"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_remove_blocked: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_list_calls: {
        parameters: {
            query?: {
                attention?: boolean | null;
                category?: components["schemas"]["CallCategory"] | null;
                cursor?: string | null;
                from?: string | null;
                language?: string | null;
                limit?: number;
                provider?: components["schemas"]["ProviderKind"] | null;
                q?: string | null;
                risk_level?: components["schemas"]["RiskLevel"] | null;
                status?: components["schemas"]["CallStatus"] | null;
                to?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallPage"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_create_call: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateCallRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallDetail"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_delete_all: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_get_call: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallDetail"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_delete_call: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_upload_audio: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_calls_upload_audio"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TurnResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_block: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["BlockRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BlockedCaller"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_delete_content: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_continue: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OwnerActionResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_end: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OwnerActionResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_events: {
        parameters: {
            query?: {
                after_seq?: number;
            };
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LiveEvent"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_export_call: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_feedback: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FeedbackRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FeedbackRecord"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_interrupt: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["InterruptRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InterruptResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_submit_partial: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PartialRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_diagnostic_report: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_silence: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TurnResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_takeover: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OwnerActionResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_trust: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["TrustRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrustedCaller"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    calls_submit_turn: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description Call id */
                call_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TurnRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TurnResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    system_home: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HomeSummary"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    live_live_ticket: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["TicketRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TicketResponse"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    system_me: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MeView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_get_preferences: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserPreferences"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_put_preferences: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserPreferences"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserPreferences"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_safety_events: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafetyEventView"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_policies: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SafetyPolicyView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    screening_config: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScreeningConfig"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    screening_event: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ScreeningEventRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallListItem"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    screening_lists: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScreeningLists"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    simulator_create_simulated_call: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateCallRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallDetail"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    simulator_providers: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProviderOption"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    simulator_replay: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReplayRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReplayResult"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    simulator_scenarios: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScenarioSummary"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    simulator_create_scenario: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateScenarioRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScenarioSummary"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    system_system_status: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemStatus"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_list_trusted: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrustedCaller"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_add_trusted: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ListNumberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TrustedCaller"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    safety_remove_trusted: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_voice_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_voice_consent: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VoiceConsentView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_voice_enroll: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VoiceEnrollRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VoiceProfileView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_voice_status: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VoiceProfileView"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    account_voices: {
        parameters: {
            query?: {
                locale?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VoiceOption"][];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    health_healthz: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    health_metrics: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": string;
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/plain": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
    health_readyz: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Payload too large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Unsupported media type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Validation error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Rate limited */
            429: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
            /** @description Provider unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorEnvelope"];
                };
            };
        };
    };
}
