"""The latency diagnostic. The conversation records below are hand-built test
inputs in the shape ElevenLabs documents, not results from a real call."""

from __future__ import annotations

from warmline.voice import timing


def record(duration: int, metrics: dict | None) -> dict:
    turn_metrics = (
        {"metrics": metrics, "convai_tts_model": "eleven_v3_conversational"} if metrics else None
    )
    return {
        "termination_reason": "end_call tool was called.",
        "metadata": {"call_duration_secs": duration},
        "transcript": [
            {"role": "agent", "message": "Hi, I'm an AI assistant.", "time_in_call_secs": 0},
            {"role": "user", "message": "Go on.", "time_in_call_secs": 5},
            {
                "role": "agent",
                "message": "We work with companies on press coverage.",
                "time_in_call_secs": 8,
                "conversation_turn_metrics": turn_metrics,
            },
        ],
    }


def test_each_metric_is_summarised_with_its_median_and_worst_case():
    lines = timing.summarise(record(40, {"convai_llm_service_ttfb": {"elapsed_time": 1.25}}))

    text = "\n".join(lines)
    assert "convai_llm_service_ttfb 1.25s" in text
    assert "median 1.25s, worst 1.25s, 1 turns" in text
    assert "tts model eleven_v3_conversational" in text


def test_metrics_repeated_on_a_tool_call_turn_are_not_counted_twice():
    details = record(40, {"convai_llm_service_ttfb": {"elapsed_time": 1.25}})
    details["transcript"].append(
        {
            "role": "agent",
            "message": None,
            "time_in_call_secs": 9,
            "conversation_turn_metrics": {
                "metrics": {
                    "convai_llm_service_ttfb": {"elapsed_time": 1.25},
                    "convai_llm_tool_request_generation_latency": {"elapsed_time": 2.45},
                }
            },
        }
    )

    text = "\n".join(timing.summarise(details))

    assert "convai_llm_service_ttfb: median 1.25s, worst 1.25s, 1 turns" in text
    assert "convai_llm_tool_request_generation_latency: median 2.45s" in text
    assert "(no speech)" in text


def test_a_call_longer_than_the_promised_minute_is_pointed_out():
    lines = timing.summarise(record(95, None))

    assert any("promises under a minute; this call lasted 95s" in line for line in lines)


def test_a_call_inside_the_minute_is_not_flagged():
    lines = timing.summarise(record(40, None))

    assert not any("promises under a minute" in line for line in lines)


def test_missing_metrics_are_reported_rather_than_invented():
    lines = timing.summarise(record(40, None))

    assert lines[-1].strip() == "ElevenLabs recorded no per-turn metrics for this conversation."


def test_the_command_needs_a_conversation_id(capsys):
    assert timing.main([]) == 2
    assert "usage" in capsys.readouterr().out
