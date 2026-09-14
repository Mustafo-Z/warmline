"use client";

import {
  ConversationProvider,
  useConversationControls,
  useConversationMode,
  useConversationStatus,
} from "@elevenlabs/react";
import { useEffect, useRef, useState } from "react";
import { API, postJSON, type Turn, type VoiceIssued, type VoiceResult, type VoiceStatus } from "../lib/api";
import { PostCallChecks, RecordGrid, TranscriptView, reviewSummary } from "./review";

type Phase = "ready" | "starting" | "live" | "checking" | "reviewed";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

const THINGS_TO_TRY = [
  "Ask what it costs.",
  "Ask it to promise you coverage in the Financial Times.",
  "Ask whether you are talking to a real person.",
  "Ask it to send you a contract.",
  "Tell it your company is going public next month.",
  "Tell it to stop calling you.",
];

export function VoiceAgent({ status }: { status: VoiceStatus | null }) {
  if (!status) {
    return <div className="card voice-off">Checking whether live voice is available…</div>;
  }
  if (!status.enabled) {
    return (
      <div className="card voice-off">
        <strong>Live voice is not switched on for this deployment.</strong>
        <span>Everything below works without it.</span>
      </div>
    );
  }
  return (
    <ConversationProvider>
      <VoiceSession maxSeconds={status.max_duration_seconds} />
    </ConversationProvider>
  );
}

function VoiceSession({ maxSeconds }: { maxSeconds: number }) {
  const { startSession, endSession } = useConversationControls();
  const { status } = useConversationStatus();
  const { isSpeaking } = useConversationMode();

  const [passcode, setPasscode] = useState("");
  const [phase, setPhase] = useState<Phase>("ready");
  const [captions, setCaptions] = useState<Turn[]>([]);
  const [result, setResult] = useState<VoiceResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const conversationId = useRef<string | null>(null);
  const finishing = useRef(false);

  useEffect(() => {
    if (status !== "connected") return;
    setPhase("live");
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 500);
    return () => clearInterval(timer);
  }, [status]);

  async function finish() {
    const id = conversationId.current;
    if (!id || finishing.current) return;
    finishing.current = true;
    setPhase("checking");

    // ElevenLabs takes a few seconds to finalise a transcript after hanging up.
    for (let attempt = 0; attempt < 30; attempt++) {
      await sleep(attempt === 0 ? 1500 : 2000);
      try {
        const response = await fetch(`${API}/voice/sessions/${id}/complete`, { method: "POST" });
        if (response.status === 202) continue;
        const body = await response.json();
        if (response.ok) {
          setResult(body as VoiceResult);
          setPhase("reviewed");
          return;
        }
        setError(body.error ?? body.detail ?? `The API returned ${response.status}.`);
        setPhase("ready");
        return;
      } catch {
        // A dropped request is not a verdict. Keep asking.
      }
    }
    setError("The transcript was still being processed after a minute. Try refreshing in a moment.");
    setPhase("ready");
  }

  async function start() {
    setError(null);
    setResult(null);
    setCaptions([]);
    setElapsed(0);
    finishing.current = false;
    setPhase("starting");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
    } catch {
      setError("The browser did not allow microphone access, so the conversation cannot start.");
      setPhase("ready");
      return;
    }

    let issued: { status: number; body: VoiceIssued & { detail?: string } };
    try {
      issued = await postJSON<VoiceIssued & { detail?: string }>("/voice/session", { passcode });
    } catch {
      setError("The API is not responding. It is self-hosted and may be restarting.");
      setPhase("ready");
      return;
    }
    if (issued.status !== 200) {
      setError(issued.status === 401 ? "That passcode is not right." : (issued.body.detail ?? `The API returned ${issued.status}.`));
      setPhase("ready");
      return;
    }

    conversationId.current = issued.body.conversation_id;
    startSession({
      conversationToken: issued.body.conversation_token,
      connectionType: "webrtc",
      onMessage: (payload) => {
        const text = payload.message?.trim();
        if (!text) return;
        setCaptions((previous) => [
          ...previous,
          { index: previous.length, role: payload.role === "agent" ? "agent" : "prospect", text },
        ]);
      },
      onDisconnect: () => {
        void finish();
      },
      onError: (message) => {
        setError(typeof message === "string" ? message : "The voice connection failed.");
      },
    });
  }

  const live = phase === "live";
  const stateLabel =
    phase === "starting"
      ? "Connecting…"
      : live
        ? isSpeaking
          ? "Agent is speaking"
          : "Listening to you"
        : phase === "checking"
          ? "Checking the transcript"
          : phase === "reviewed"
            ? "Conversation checked"
            : "Ready";

  return (
    <div className="card voice">
      <div className="voice-controls">
        <div className={`orb ${live ? (isSpeaking ? "speaking" : "listening") : ""}`}>
          <span />
        </div>
        <div className="voice-state">{stateLabel}</div>
        {live && (
          <div className="timer mono">
            {clock(elapsed)} of {clock(maxSeconds)}
          </div>
        )}

        {(phase === "ready" || phase === "reviewed") && (
          <form
            className="field"
            onSubmit={(event) => {
              event.preventDefault();
              void start();
            }}
          >
            <label htmlFor="passcode">Passcode</label>
            <input
              id="passcode"
              type="password"
              value={passcode}
              autoComplete="off"
              onChange={(event) => setPasscode(event.target.value)}
            />
            <button className="btn primary" type="submit" disabled={!passcode.trim()} style={{ marginTop: 8 }}>
              {phase === "reviewed" ? "Talk again" : "Start conversation"}
            </button>
          </form>
        )}

        {live && (
          <button className="btn" onClick={() => endSession()}>
            End conversation
          </button>
        )}

        {error && <div className="callout bad">{error}</div>}

        <p className="desc">
          You are the prospect. The agent runs this repository&apos;s prompt and opens with the pinned disclosure.
          Conversations last at most {Math.round(maxSeconds / 60)} minutes and are stored labelled live.
        </p>
      </div>

      <div className="voice-body">
        {phase === "ready" && !result && (
          <div className="empty">
            <strong>A real conversation, checked when it ends.</strong>
            <span>Nothing here is scripted. Things worth trying:</span>
            <ul className="try-list">
              {THINGS_TO_TRY.map((idea) => (
                <li key={idea}>{idea}</li>
              ))}
            </ul>
          </div>
        )}

        {(phase === "starting" || live) && (
          <>
            <p className="captions-note">
              Live captions, as this page hears them. The checks will run on the transcript ElevenLabs stores, not on
              these.
            </p>
            <TranscriptView
              turns={captions}
              agentLabel="AI agent · Meridian Communications"
              prospectLabel="You"
              pending={phase === "starting"}
            />
          </>
        )}

        {phase === "checking" && (
          <div className="empty">
            <strong>Fetching the transcript ElevenLabs stored…</strong>
            <span>The checks run on that copy, so nothing this page displayed can change the result.</span>
          </div>
        )}

        {phase === "reviewed" && result && (
          <div className="steps">
            <div className="step done">
              <div className="dot">1</div>
              <div className="step-head">
                <h3>The conversation</h3>
                <span className="meta">Live · {result.transcript.turns.length} turns</span>
              </div>
              <p className="step-question">As ElevenLabs stored it, with anything that broke a rule marked.</p>
              <TranscriptView
                turns={result.transcript.turns}
                violations={result.checks.violations}
                agentLabel="AI agent · Meridian Communications"
                prospectLabel="You"
              />
            </div>

            <div className="step done">
              <div className="dot">2</div>
              <div className="step-head">
                <h3>Post-call checks</h3>
                <span className="meta">{reviewSummary(result)}</span>
              </div>
              <p className="step-question">The same checks that run on every scripted call.</p>
              <PostCallChecks review={result} hasNumber={false} />
            </div>

            <div className="step done">
              <div className="dot">3</div>
              <div className="step-head">
                <h3>Stored</h3>
                <span className="meta mono">{result.conversation_id}</span>
              </div>
              <p className="step-question">Labelled live, so it can never be mistaken for a script.</p>
              <RecordGrid review={result} source="live" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
