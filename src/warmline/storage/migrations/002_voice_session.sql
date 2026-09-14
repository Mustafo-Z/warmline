-- Browser voice sessions with the live agent.
--
-- Kept apart from call_attempt on purpose. A call_attempt is an outbound call
-- to someone who did not ask for it, which is what the pre-dial gate exists to
-- control. A voice session is started by the person talking, in their own
-- browser, after entering a passcode: there is no number, no consent question
-- and no calling window. Putting both in one table would invite someone to read
-- a browser session as a call that skipped the gate.
--
-- What they share is everything after the conversation: the transcript is
-- checked by the same post-call code, and the result is stored the same way.

CREATE TABLE voice_session (
    id                   TEXT PRIMARY KEY,
    -- Issued by ElevenLabs alongside the session token. Only conversations this
    -- service started can be submitted for checking.
    conversation_id      TEXT NOT NULL UNIQUE,
    agent_id             TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('issued', 'processed', 'failed')),
    issued_at            TEXT NOT NULL,
    processed_at         TEXT,
    transcript_json      TEXT,
    -- Always 'live' once processed: this transcript came from a real
    -- conversation with a real model, and is labelled so everywhere it goes.
    transcript_source    TEXT CHECK (transcript_source IS NULL OR transcript_source = 'live'),
    disclosure_ok        INTEGER,
    violations_json      TEXT,
    classifications_json TEXT,
    outcome_json         TEXT,
    error                TEXT
);

CREATE INDEX idx_voice_session_issued ON voice_session(issued_at);
