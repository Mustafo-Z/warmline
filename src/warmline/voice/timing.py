"""Where the time went in a live conversation.

    python -m warmline.voice.timing <conversation_id> [<conversation_id> ...]

Run on the machine that holds the ElevenLabs key. Prints, for each turn, when
it happened in the call and every per-turn metric ElevenLabs recorded — the
language model's and the speech model's time to first byte among them — then
the median and worst case of each metric across the call.

Written after a live call felt slow, so that the fix could be chosen from
measurements instead of guesses: the usual suspects are the language model,
the speech model and the voice, and they call for different changes.

It also checks the one claim in the opening line that the call's own metadata
can verify: "I'll keep this under a minute."
"""

from __future__ import annotations

import os
import statistics
import sys

from warmline.envfile import load_env_file
from warmline.voice.elevenlabs import ElevenLabsClient, ElevenLabsError

#: The pinned opening promises the call will be under a minute.
PROMISED_SECONDS = 60


def language_models(metadata: dict) -> list[str]:
    """The language models ElevenLabs billed the call for.

    The per-turn metrics do not say which model produced a turn, so a before
    and after comparison of a model change needs this to show which side of the
    change a call was on.
    """
    usage = (metadata.get("charging") or {}).get("llm_usage") or {}
    names: set[str] = set()
    for generation in usage.values():
        if isinstance(generation, dict):
            names.update((generation.get("model_usage") or {}).keys())
    return sorted(names)


def summarise(details: dict) -> list[str]:
    metadata = details.get("metadata") or {}
    duration = metadata.get("call_duration_secs")
    models = language_models(metadata)
    lines = [
        f"  duration {duration}s, ended by: {details.get('termination_reason') or 'not recorded'}",
        f"  language model: {', '.join(models) if models else 'not recorded'}",
    ]
    if isinstance(duration, (int, float)) and duration > PROMISED_SECONDS:
        lines.append(f"  the opening line promises under a minute; this call lasted {duration}s")

    seen: dict[str, list[float]] = {}
    previous: dict[str, float] = {}
    for item in details.get("transcript") or []:
        at = item.get("time_in_call_secs")
        role = item.get("role", "?")
        text = (item.get("message") or "").strip().replace("\n", " ")
        preview = text[:56] + ("…" if len(text) > 56 else "") if text else "(no speech)"
        turn_metrics = item.get("conversation_turn_metrics") or {}
        metrics = turn_metrics.get("metrics") or {}
        current: dict[str, float] = {}
        parts = []
        for name, value in sorted(metrics.items()):
            elapsed = value.get("elapsed_time") if isinstance(value, dict) else None
            if not isinstance(elapsed, (int, float)):
                continue
            current[name] = elapsed
            # A turn with no speech, such as the end_call tool call, carries a
            # copy of the previous turn's metrics. Counting the copy again would
            # skew the medians, so only what is new on that turn is kept.
            if not text and previous.get(name) == elapsed:
                continue
            seen.setdefault(name, []).append(elapsed)
            parts.append(f"{name} {elapsed:.2f}s")
        if current:
            previous = current
        model = turn_metrics.get("convai_tts_model")
        if model:
            parts.append(f"tts model {model}")
        when = f"{at}s" if at is not None else "?"
        suffix = f"   [{'; '.join(parts)}]" if parts else ""
        lines.append(f"  {when:>5} {role:<6} {preview}{suffix}")

    if seen:
        lines.append("  across the call:")
        for name, values in sorted(seen.items()):
            lines.append(
                f"    {name}: median {statistics.median(values):.2f}s,"
                f" worst {max(values):.2f}s, {len(values)} turns"
            )
    else:
        lines.append("  ElevenLabs recorded no per-turn metrics for this conversation.")
    return lines


def main(argv: list[str] | None = None) -> int:
    conversation_ids = list(sys.argv[1:] if argv is None else argv)
    if not conversation_ids:
        print("usage: python -m warmline.voice.timing <conversation_id> [<conversation_id> ...]")
        return 2

    load_env_file()
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        print("ELEVENLABS_API_KEY is not set.")
        return 1

    client = ElevenLabsClient(api_key)
    status = 0
    for conversation_id in conversation_ids:
        print(f"\n{conversation_id}")
        try:
            details = client.get_conversation_details(conversation_id)
        except ElevenLabsError as error:
            print(f"  {error}")
            status = 1
            continue
        print("\n".join(summarise(details)))
    return status


if __name__ == "__main__":
    sys.exit(main())
