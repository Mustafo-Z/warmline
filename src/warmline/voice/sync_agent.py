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
from warmline.voice.elevenlabs import ElevenLabsClient

#: A premade ElevenLabs voice. Override with ELEVENLABS_VOICE_ID.
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

#: Anthropic, as the stack this is written for uses. Override with ELEVENLABS_LLM.
DEFAULT_LLM = "claude-sonnet-4-5"


def build_definition(agent: AgentConfig, *, llm: str, voice_id: str) -> dict:
    return {
        "name": agent.name,
        "conversation_config": {
            "agent": {
                # The pinned disclosure, spoken before the model says anything.
                "first_message": agent.first_turn,
                "language": agent.language,
                "prompt": {"prompt": agent.system_prompt, "llm": llm},
            },
            "tts": {"voice_id": voice_id},
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
        voice_id=os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID),
    )
    agent_id, created = sync(
        ElevenLabsClient(api_key), definition, agent_id=os.environ.get("ELEVENLABS_AGENT_ID")
    )
    if created:
        remember_agent_id(env_path, agent_id)

    print(f"{'Created' if created else 'Updated'} agent {agent_id}")
    print(f"  opening line: {agent.first_turn}")
    print(f"  model: {definition['conversation_config']['agent']['prompt']['llm']}")
    print(f"  max call length: {agent.max_duration_seconds}s, auth required: yes")
    if created:
        print(f"  agent id written to {env_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
