#!/usr/bin/env python3
"""CLI: run the Lead Researcher agent on a slice of leads.

Examples:
  # score 5 leads for the demo client (default)
  python scripts/run_lead_agent.py

  # score 10 leads for a custom client
  python scripts/run_lead_agent.py --client-slug client-acme --batch-size 10

  # resume a previous run by passing its thread_id
  python scripts/run_lead_agent.py --thread-id lead-research-abc123def456

  # Use a different model
  python scripts/run_lead_agent.py --model anthropic:claude-opus-4-7

Requires:
  - MONGO_URI env or .env loaded.
  - ANTHROPIC_API_KEY env (or whatever provider matches --model).
"""

from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    p = argparse.ArgumentParser(description="Run the SolarReach Lead Researcher agent.")
    p.add_argument("--client-slug", default="client-greensolar-uk")
    p.add_argument("--batch-size", type=int, default=5)
    p.add_argument("--thread-id", default=None,
                   help="Pass an existing thread_id to resume a checkpointed run.")
    p.add_argument("--model", default=None, help="Override SOLARREACH_AGENT_MODEL env.")
    p.add_argument("--with-store", action="store_true",
                   help="Enable the MongoDB long-term store for cross-session memory.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Defer the agent import — heavy.
    from lead_agent.agent import DEFAULT_MODEL, run_lead_agent_session

    out = run_lead_agent_session(
        client_slug=args.client_slug,
        batch_size=args.batch_size,
        thread_id=args.thread_id,
        use_long_term_store=args.with_store,
        model=args.model or DEFAULT_MODEL,
    )

    print()
    print("=" * 72)
    print(f"thread_id     : {out['thread_id']}")
    print(f"messages      : {out['message_count']}")
    print(f"final message : {out['final_message']}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
