import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from signalhub import Agent


def main() -> None:
    api_key = os.getenv("SIGNALHUB_API_KEY", "")
    if not api_key:
        raise RuntimeError("Set SIGNALHUB_API_KEY before running demo")

    agent = Agent(api_key=api_key, base_url=os.getenv("SIGNALHUB_BASE_URL", "http://localhost:8000"))

    discovered = agent.discover("deploy related errors")
    print("Discover results:")
    for item in discovered.get("results", []):
        print("-", item.get("metadata", {}).get("topic"), "::", item.get("snippet", "")[:120])

    print("\nSubscribing to story topic for 20 seconds...")
    ws = agent.subscribe(
        "marketplace.ops.incident.story.v1",
        lambda event: print("story-event:", event.get("payload_json", event.get("payload"))),
    )
    time.sleep(20)
    ws.close()

    now = datetime.now(UTC)
    since = (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    until = now.isoformat().replace("+00:00", "Z")
    replay_rows = agent.replay("marketplace.ops.incident.story.v1", since=since, until=until)
    print(f"\nReplay rows in last 30m: {len(replay_rows)}")


if __name__ == "__main__":
    main()
