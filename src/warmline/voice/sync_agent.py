"""Create or update the ElevenLabs agent from the files in agent/.

    python -m warmline.voice.sync_agent

Run on the machine that holds the key. The agent's prompt, opening line and
call length come from the repository, so what the live agent is told is the
same text a reviewer reads in a diff — not something assembled by hand in a
vendor dashboard and never seen again.

The first run creates the agent and writes its id into .env. Later runs update
the same agent in place.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from warmline.agent import AgentConfig, load_agent_config
from warmline.envfile import default_env_path, load_env_file
from warmline.voice.elevenlabs import ElevenLabsClient, ElevenLabsError

#: Anthropic, as the stack this is written for uses. Override with ELEVENLABS_LLM.
DEFAULT_LLM = "claude-sonnet-4-5"


def build_definition(agent: AgentConfig, *, llm: str, voice_id: str | None = None) -> dict:
    return {
        "name": agent.name,
        "conversation_config": {
            "agent": {
                # The pinned disclosure, spoken before the model says anything.
                "first_message": agent.first_turn,
                "language": agent.language,
                "prompt": {
                    "prompt": agent.system_prompt,
                    "llm": llm,
                    # Lets the agent hang up. Agents created in the ElevenLabs
                    # dashboard have this by default; agents created through
                    # the API do not, which is why the first version could only
                    # wait for the caller to end the conversation.
                    "built_in_tools": {
                        "end_call": {
                            "type": "system",
                            "name": "end_call",
                            "description": agent.end_call_when,
                            "params": {"system_tool_type": "end_call"},
                        }
                    },
                },
            },
            # The voice lives in agent/agent_config.json, so changing how the
            # agent sounds is a reviewed edit, like changing what it says.
            # ELEVENLABS_VOICE_ID can override it for trying voices out.
            "tts": {
                "voice_id": voice_id or agent.voice_id,
                "model_id": agent.tts_model,
                "speed": agent.voice_speed,
            },
            "conversation": {"max_duration_seconds": agent.max_duration_seconds},
        },
        # Sessions can only be opened with a token this service issued after
        # checking the passcode. Without this, anyone with the agent id could
        # start a conversation and spend the account's minutes.
        "platform_settings": {"auth": {"enable_auth": True}},
    }


def sync(client, definition: dict, *, agent_id: str | None) -> tuple[str, bool]:
    """Returns (agent_id, created)."""
    if agent_id:
        client.update_agent(agent_id, definition)
        return agent_id, False
    return client.create_agent(definition), True


def remember_agent_id(env_path: Path, agent_id: str) -> None:
    """Write ELEVENLABS_AGENT_ID into .env, replacing any existing line."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    kept = [line for line in lines if not line.strip().startswith("ELEVENLABS_AGENT_ID=")]
    kept.append(f"ELEVENLABS_AGENT_ID={agent_id}")
    env_path.write_text("\n".join(kept) + "\n")
    env_path.chmod(0o600)


def main() -> int:
    env_path = default_env_path()
    load_env_file(env_path)

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        print(f"ELEVENLABS_API_KEY is not set. Add it to {env_path} and run this again.")
        return 1

    agent = load_agent_config()
    definition = build_definition(
        agent,
        llm=os.environ.get("ELEVENLABS_LLM", DEFAULT_LLM),
        voice_id=os.environ.get("ELEVENLABS_VOICE_ID") or None,
    )
    try:
        agent_id, created = sync(
            ElevenLabsClient(api_key), definition, agent_id=os.environ.get("ELEVENLABS_AGENT_ID")
        )
    except ElevenLabsError as error:
        # ElevenLabs rejects the whole update, so a failure here leaves the
        # agent exactly as it was. Say so, and say what to do, rather than
        # printing a traceback.
        print(f"ElevenLabs refused the update, so the agent is unchanged.\n\n  {error}\n")
        if "voice_not_found" in str(error):
            voice_id = definition["conversation_config"]["tts"]["voice_id"]
            print(
                f"Voice {voice_id} is not available to this account. A voice from the\n"
                "Voice Library has to be added to your account before an agent can use\n"
                "it (Voice Library, then 'Add to my voices'), and free plans cannot use\n"
                "Voice Library voices through the API at all. Put a voice ID from My Voices\n"
                "in agent/agent_config.json, or try one first with ELEVENLABS_VOICE_ID in .env."
            )
        return 1
    if created:
        remember_agent_id(env_path, agent_id)

    print(f"{'Created' if created else 'Updated'} agent {agent_id}")
    print(f"  opening line: {agent.first_turn}")
    print(f"  model: {definition['conversation_config']['agent']['prompt']['llm']}")
    tts = definition["conversation_config"]["tts"]
    print(f"  voice: {agent.voice_name or tts['voice_id']}, speech model {tts['model_id']}")
    print(f"  max call length: {agent.max_duration_seconds}s, auth required: yes")
    if created:
        print(f"  agent id written to {env_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
