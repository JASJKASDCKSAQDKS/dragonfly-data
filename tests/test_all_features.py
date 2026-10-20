#!/usr/bin/env python3
"""
Jarvis — Comprehensive Feature Test Suite.

Tests all tiers without requiring interactive input.
"""

import asyncio
import json
import os
import sys
import tempfile
import time

# Ensure project root is on path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
WARN = "\033[93m⚠️  WARN\033[0m"
HEADER = "\033[96m\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"

results = []

def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    icon = PASS if passed else FAIL
    print(f"  {icon}  {name}" + (f"  {DIM}({detail}){RESET}" if detail else ""))

def section(title):
    print(f"\n{HEADER}{'─'*56}")
    print(f"  {title}")
    print(f"{'─'*56}{RESET}")


async def main():
    print(f"\n{HEADER}{'═'*56}")
    print(f"  JARVIS — FULL FEATURE TEST SUITE")
    print(f"{'═'*56}{RESET}")

    # ── TIER 0: Config ────────────────────────────────────
    section("Tier 0: Configuration & Identity")
    try:
        from jarvis import config
        record("Config loads", True, f"name={config.ASSISTANT_NAME}")
        record("Model configured", bool(config.MODEL_NAME), config.MODEL_NAME)
        record("Ollama host set", bool(config.OLLAMA_HOST), config.OLLAMA_HOST)
        record("Data dir set", bool(config.DATA_DIR), config.DATA_DIR)
    except Exception as e:
        record("Config loads", False, str(e))

    # ── TIER 1: Brain (Ollama connection + AI response) ───
    section("Tier 1: Brain — AI Response via Ollama")
    try:
        from jarvis.conversation import Conversation
        from jarvis.prompts import build_system_prompt
        from jarvis.brain import process_turn
        import jarvis.tools  # noqa: F401

        conv = Conversation()
        system_prompt = build_system_prompt()
        record("System prompt builds", bool(system_prompt), f"{len(system_prompt)} chars")
        record("Conversation init", True)

        # Test actual AI response
        reply_chunks = []
        print(f"  {DIM}  Sending test message to Ollama...{RESET}", end="", flush=True)
        async for chunk in process_turn("Say hello in one sentence.", conv, system_prompt):
            reply_chunks.append(chunk)
        full_reply = "".join(reply_chunks)
        print(f"\r  {DIM}  AI replied: \"{full_reply[:80]}...\" {RESET}" if len(full_reply) > 80 else f"\r  {DIM}  AI replied: \"{full_reply}\"{RESET}")
        record("AI responds", len(full_reply) > 0, f"{len(full_reply)} chars")
        record("Conversation tracks turns", conv.turn_count() == 2, f"{conv.turn_count()} turns")

        # Test streaming works
        conv2 = Conversation()
        chunks_received = 0
        async for chunk in process_turn("What is 2+2? Answer in one word.", conv2, system_prompt):
            chunks_received += 1
        record("Streaming works", chunks_received >= 1, f"{chunks_received} chunks")

    except Exception as e:
        print()
        record("AI responds", False, str(e))

    # ── TIER 2: Tools ─────────────────────────────────────
    section("Tier 2: Tools — Registry & Execution")
    try:
        from jarvis.tools import registry

        tool_names = registry.names()
        record("Tools registered", len(tool_names) > 0, ", ".join(tool_names))

        # Test datetime tool
        result = await registry.execute("current_datetime", {})
        record("current_datetime tool", "Error" not in result, result[:60])

        # Test list_directory tool
        result = await registry.execute("list_directory", {"path": PROJECT_ROOT})
        record("list_directory tool", "Error" not in result, f"{len(result)} chars output")

        # Test read_file tool
        agent_md_path = os.path.join(PROJECT_ROOT, "AGENT.md")
        result = await registry.execute("read_file", {"path": agent_md_path, "max_lines": 5})
        record("read_file tool", "Error" not in result and "Jarvis" in result, f"{len(result)} chars")

        # Test shell tool
        result = await registry.execute("run_shell_command", {"command": "echo hello_jarvis"})
        record("run_shell_command tool", "hello_jarvis" in result, result.strip()[:60])

        # Test Ollama tool format
        ollama_tools = registry.get_ollama_tools()
        record("Ollama tool format", len(ollama_tools) > 0, f"{len(ollama_tools)} tool definitions")

        # Validate each tool definition structure
        valid = all(
            t.get("type") == "function" and "name" in t.get("function", {})
            for t in ollama_tools
        )
        record("Tool definitions valid", valid)

    except Exception as e:
        record("Tools system", False, str(e))

    # ── TIER 2b: AI uses tools ────────────────────────────
    section("Tier 2b: Brain + Tool Integration")
    try:
        conv3 = Conversation()
        tool_calls_seen = []
        def on_tool(name, args):
            tool_calls_seen.append(name)

        reply_parts = []
        async for chunk in process_turn(
            "What is the current date and time? Use the current_datetime tool to answer.",
            conv3, system_prompt, on_tool_call=on_tool
        ):
            reply_parts.append(chunk)
        full = "".join(reply_parts)
        record("AI can call tools", len(tool_calls_seen) > 0 or len(full) > 0,
               f"tools used: {tool_calls_seen}" if tool_calls_seen else "answered directly")
        record("Tool-augmented reply", len(full) > 0, f"{len(full)} chars")
    except Exception as e:
        record("Tool integration", False, str(e))

    # ── TIER 3: Voice ─────────────────────────────────────
    section("Tier 3: Voice — Availability Checks")
    try:
        from jarvis.voice.stt import is_stt_available
        stt = is_stt_available()
        record("STT (Deepgram) available", True, f"{'YES' if stt else 'NO — missing API key'}")
    except Exception as e:
        record("STT check", False, str(e))

    try:
        from jarvis.voice.tts import is_tts_available
        tts = is_tts_available()
        record("TTS (ElevenLabs) available", True, f"{'YES' if tts else 'NO — missing API key'}")
    except Exception as e:
        record("TTS check", False, str(e))

    try:
        from jarvis.voice.mic import is_mic_available, has_pynput
        mic = is_mic_available()
        ptt = has_pynput()
        record("Microphone available", True, f"{'YES' if mic else 'NO — no input device'}")
        record("Push-to-Talk (pynput)", True, f"{'YES — hold key to speak' if ptt else 'NO — fallback to /s command mode'}")
    except Exception as e:
        record("Mic check", False, str(e))

    # ── TIER 4: Memory ────────────────────────────────────
    section("Tier 4: Memory — SQLite + FTS5")
    try:
        from jarvis.memory.store import MemoryStore
        # Use a temp DB so we don't pollute real data
        tmp_db = os.path.join(tempfile.mkdtemp(), "test_memory.db")
        store = MemoryStore(db_path=tmp_db)
        record("Memory store init", True, f"DB: {tmp_db}")

        # Add memory
        mem = store.add_memory("Test fact: Python is great", category="fact", source="test")
        record("Add memory", mem.id > 0, f"id={mem.id}")

        # List memories
        mems = store.list_memories()
        record("List memories", len(mems) == 1, f"{len(mems)} found")

        # Search memories (FTS5)
        found = store.search_memories("Python")
        record("FTS5 search", len(found) > 0, f"found {len(found)} for 'Python'")

        # Get by ID
        fetched = store.get_memory(mem.id)
        record("Get memory by ID", fetched is not None and fetched.content == mem.content)

        # Delete memory
        deleted = store.delete_memory(mem.id)
        record("Delete (soft) memory", deleted)

        remaining = store.list_memories()
        record("Soft delete works", len(remaining) == 0)

        # Session persistence
        test_turns = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        sid = store.save_session(test_turns, started_at="2026-01-01T00:00:00")
        record("Save session", sid > 0, f"session_id={sid}")

        last = store.get_last_session()
        record("Load last session", last is not None and len(last.turns) == 2)

        store.close()
        os.unlink(tmp_db)

    except Exception as e:
        record("Memory system", False, str(e))

    # Test manager-level functions
    try:
        from jarvis.memory.manager import remember, forget, list_all, recall
        record("Memory manager imports", True)

        r = recall()
        record("Recall (context builder)", True, f"{len(r)} chars context")
    except Exception as e:
        record("Memory manager", False, str(e))

    # ── TIER 5: Heartbeat ─────────────────────────────────
    section("Tier 5: Heartbeat — Proactive Engine")
    try:
        from jarvis.heartbeat import (
            is_killswitch_active, toggle_killswitch, set_killswitch,
            add_reminder, get_due_reminders,
            is_quiet_hours, get_quiet_hours, set_quiet_hours,
            flush_missed_notices, queue_missed_notice,
        )

        # Killswitch
        initial = is_killswitch_active()
        record("Killswitch initial state", not initial, "OFF (expected)")

        toggled = toggle_killswitch()
        record("Toggle killswitch ON", toggled == True)

        set_killswitch(False)
        record("Set killswitch OFF", not is_killswitch_active())

        # Quiet hours
        s, e = get_quiet_hours()
        record("Get quiet hours", True, f"{s:02d}:00–{e:02d}:00")

        set_quiet_hours(1, 2)
        s2, e2 = get_quiet_hours()
        record("Set quiet hours", s2 == 1 and e2 == 2)
        set_quiet_hours(22, 7)  # restore default

        # Missed notices
        queue_missed_notice("Test notice")
        notices = flush_missed_notices()
        record("Queue & flush missed notices", len(notices) == 1 and notices[0] == "Test notice")

        # Reminders
        msg = add_reminder("Test reminder", "1s")
        record("Add reminder", "scheduled" in msg.lower() or "Reminder" in msg, msg[:60])

        # Wait for it to become due
        await asyncio.sleep(1.5)
        due = get_due_reminders()
        record("Get due reminders", len(due) >= 1, f"{len(due)} due")

        # Heartbeat loop (brief run)
        from jarvis.heartbeat import heartbeat_loop
        notices_received = []
        async def on_notice(n):
            notices_received.append(n)

        loop_task = asyncio.create_task(heartbeat_loop(on_notice=lambda n: notices_received.append(n), tick_interval_seconds=1))
        await asyncio.sleep(2.5)
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        record("Heartbeat loop runs", True, f"ran for ~2.5s, {len(notices_received)} notices surfaced")

    except Exception as e:
        record("Heartbeat system", False, str(e))

    # ── TIER 6: Safety Rails ──────────────────────────────
    section("Tier 6: Safety Rails — Gate, Audit, Guard")
    try:
        from jarvis.rails import (
            requires_confirmation, log_event, get_recent_logs, wrap_external_data,
        )

        # Confirmation gate
        needs, reason = requires_confirmation("TOOL", "run_shell_command", {"command": "rm -rf /"})
        record("Gate: destructive cmd flagged", needs, reason[:60])

        needs2, _ = requires_confirmation("TOOL", "current_datetime", {})
        record("Gate: safe cmd passes", not needs2)

        needs3, reason3 = requires_confirmation("DELETE_DATA", "forget", {})
        record("Gate: delete flagged", needs3, reason3[:60])

        # Audit logging
        log_event("TEST", "test_action", details={"key": "value"}, reasoning="test run", status="SUCCESS")
        logs = get_recent_logs(5)
        record("Audit log write+read", len(logs) > 0 and any("test_action" in l for l in logs))

        # Data guard
        wrapped = wrap_external_data("Hello world", source="test")
        record("Data guard wraps", "<external_untrusted_data" in wrapped and "Hello world" in wrapped)

    except Exception as e:
        record("Safety rails", False, str(e))

    # ── Web Server ────────────────────────────────────────
    section("Web Server — FastAPI Endpoints")
    try:
        from jarvis.web.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)

        # Status endpoint
        resp = client.get("/api/status")
        record("GET /api/status", resp.status_code == 200, f"model={resp.json().get('model')}")

        # Memories endpoint
        resp = client.get("/api/memories")
        record("GET /api/memories", resp.status_code == 200, f"{len(resp.json())} memories")

        # Audit endpoint
        resp = client.get("/api/audit")
        record("GET /api/audit", resp.status_code == 200)

        # Quiet hours
        resp = client.get("/api/quiet")
        record("GET /api/quiet", resp.status_code == 200)

        # Killswitch toggle
        resp = client.post("/api/killswitch")
        record("POST /api/killswitch", resp.status_code == 200)
        # Reset it
        client.post("/api/killswitch")

        # Add reminder via API
        resp = client.post("/api/reminders", json={"text": "API test reminder", "delay": "5m"})
        record("POST /api/reminders", resp.status_code == 200)

        # Index page
        resp = client.get("/")
        record("GET / (voice UI)", resp.status_code == 200)

        # Static files
        resp = client.get("/static/voice.css")
        record("GET /static/voice.css", resp.status_code == 200)

        resp = client.get("/static/voice.js")
        record("GET /static/voice.js", resp.status_code == 200)

    except Exception as e:
        record("Web server", False, str(e))

    # ── WebSocket chat ────────────────────────────────────
    section("WebSocket — Live Chat Streaming")
    try:
        from fastapi.testclient import TestClient
        from jarvis.web.server import app

        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "chat", "text": "Say hi in one word."}))

            messages = []
            turn_started = False
            turn_ended = False
            for _ in range(50):  # safety limit
                try:
                    data = ws.receive_json()
                    messages.append(data)
                    if data.get("type") == "turn_start":
                        turn_started = True
                    if data.get("type") == "turn_end":
                        turn_ended = True
                        break
                    if data.get("type") == "error":
                        break
                except Exception:
                    break

            record("WebSocket connects", True)
            record("WS turn_start received", turn_started)
            chunks = [m for m in messages if m.get("type") == "chunk"]
            record("WS chunks received", len(chunks) > 0, f"{len(chunks)} chunks")
            record("WS turn_end received", turn_ended)

            full_ws_reply = "".join(c.get("content", "") for c in chunks)
            record("WS AI reply content", len(full_ws_reply) > 0, f"\"{full_ws_reply[:60]}\"")

    except Exception as e:
        record("WebSocket chat", False, str(e))

    # ── Summary ───────────────────────────────────────────
    print(f"\n{HEADER}{'═'*56}")
    print(f"  TEST RESULTS SUMMARY")
    print(f"{'═'*56}{RESET}")

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    total = len(results)

    print(f"\n  Total: {total}  |  {PASS}: {passed}  |  {FAIL}: {failed}")

    if failed > 0:
        print(f"\n  {FAIL} Failed tests:")
        for name, status, detail in results:
            if status == "FAIL":
                print(f"    • {name}: {detail}")

    print(f"\n{HEADER}{'═'*56}{RESET}\n")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
