-- Warmline initial schema. SPEC 6.2.
--
-- Timestamps are UTC ISO-8601 strings ending in Z. Phone numbers are stored
-- E.164-normalised by warmline.phone.normalise_e164, which is the same
-- function the policy engine and the suppression list use, so that
-- "+971 50 123 4567" and "+971501234567" are one number everywhere.

CREATE TABLE prospect (
    id             TEXT PRIMARY KEY,
    full_name      TEXT NOT NULL,
    company        TEXT NOT NULL,
    role           TEXT,
    phone_e164     TEXT NOT NULL,
    timezone       TEXT NOT NULL,
    region_profile TEXT NOT NULL,
    language       TEXT NOT NULL DEFAULT 'en',
    -- 1 for every seeded record. Fictional data is labelled in the database,
    -- not only in the README (SPEC 2.1).
    is_fixture     INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE consent (
    id           TEXT PRIMARY KEY,
    prospect_id  TEXT NOT NULL REFERENCES prospect(id),
    lawful_basis TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    expires_at   TEXT,
    evidence     TEXT NOT NULL,
    -- Set when consent is withdrawn, and never cleared. Withdrawal is
    -- permanent and must not be "fixed" by writing a fresh consent row.
    withdrawn_at TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX idx_consent_prospect ON consent(prospect_id);

CREATE TABLE suppression_entry (
    id         TEXT PRIMARY KEY,
    phone_e164 TEXT NOT NULL UNIQUE,
    reason     TEXT NOT NULL,
    source     TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE policy_evaluation (
    id             TEXT PRIMARY KEY,
    prospect_id    TEXT NOT NULL REFERENCES prospect(id),
    phase          TEXT NOT NULL CHECK (phase IN ('pre_dial', 'post_call')),
    decision       TEXT NOT NULL CHECK (decision IN ('allow', 'block')),
    primary_reason TEXT,
    -- The decision object from SPEC 4.3, stored verbatim. The UI, the tests
    -- and the audit trail all read the same bytes.
    checks_json    TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    config_digest  TEXT NOT NULL,
    evaluated_at   TEXT NOT NULL
);

CREATE INDEX idx_evaluation_prospect ON policy_evaluation(prospect_id);

CREATE TABLE call_attempt (
    id                      TEXT PRIMARY KEY,
    prospect_id             TEXT NOT NULL REFERENCES prospect(id),
    phone_e164              TEXT NOT NULL,
    status                  TEXT NOT NULL CHECK (
                                status IN ('blocked', 'dialing', 'in_progress',
                                           'completed', 'no_answer', 'failed')),
    -- Every attempt has one, including blocked attempts: a block is a record,
    -- not the absence of one (SPEC 6.2).
    policy_evaluation_id    TEXT NOT NULL REFERENCES policy_evaluation(id),
    provider                TEXT NOT NULL,
    scenario                TEXT,
    provider_conversation_id TEXT,
    provider_call_sid       TEXT,
    requested_at            TEXT NOT NULL,
    -- NULL for blocked attempts. Only attempts that reached a provider consume
    -- attempt budget (SPEC 4.2), and this column is how that is known.
    dialed_at               TEXT,
    ended_at                TEXT,
    duration_seconds        INTEGER,
    error                   TEXT
);

CREATE INDEX idx_attempt_prospect ON call_attempt(prospect_id);
CREATE INDEX idx_attempt_number ON call_attempt(phone_e164);

CREATE TABLE call_outcome (
    id                 TEXT PRIMARY KEY,
    call_attempt_id    TEXT NOT NULL UNIQUE REFERENCES call_attempt(id),
    transcript_json    TEXT NOT NULL,
    -- 'scenario' or 'live', set by the loader rather than by whoever wrote the
    -- transcript, and surfaced in the UI. No scripted conversation can be
    -- presented as a real call (SPEC 6.2).
    transcript_source  TEXT NOT NULL CHECK (transcript_source IN ('scenario', 'live')),
    disclosure_ok      INTEGER NOT NULL,
    violations_json    TEXT NOT NULL,
    has_news           INTEGER,
    news_summary       TEXT,
    interest           TEXT NOT NULL CHECK (
                           interest IN ('interested', 'not_interested',
                                        'callback_later', 'unclear')),
    meeting_requested  INTEGER NOT NULL,
    meeting_preferences TEXT,
    opt_out_requested  INTEGER NOT NULL,
    extraction_method  TEXT NOT NULL CHECK (extraction_method IN ('deterministic', 'llm')),
    processed_at       TEXT NOT NULL,
    review_status      TEXT NOT NULL DEFAULT 'unreviewed' CHECK (
                           review_status IN ('unreviewed', 'human_ok', 'human_flagged'))
);
