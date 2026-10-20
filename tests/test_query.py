#!/usr/bin/env python3
import asyncio
import os
import sys

# Ensure project root is on path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from jarvis.brain import process_turn
from jarvis.conversation import Conversation
from jarvis.prompts import build_system_prompt


async def main():
    question = "Hello Jarvis — can you briefly introduce yourself?"
    conversation = Conversation()
    system_prompt = build_system_prompt()

    print(f"Sending question: {question}\n---\n")
    async for chunk in process_turn(question, conversation, system_prompt):
        print(chunk, end="", flush=True)

    print("\n---\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
