"""
System prompt builder.

Constructs the system prompt from the assistant's identity, personality,
and (later) memory and tool descriptions. Kept separate so each tier
can extend it without touching the brain.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jarvis import config


def _get_stable_block_cache_key() -> str:
    """Generate a cache key based on modification times of files that affect the stable block."""
    # Track identity.md file
    identity_path = os.path.join(os.path.dirname(__file__), "identity.md")
    keys = []

    if os.path.exists(identity_path):
        keys.append(f"identity:{os.path.getmtime(identity_path)}")

    # Track core_knowledge files
    core_knowledge_dir = os.path.join(os.path.dirname(__file__), "core_knowledge")
    if os.path.exists(core_knowledge_dir):
        for filename in os.listdir(core_knowledge_dir):
            if filename.endswith(".md"):
                filepath = os.path.join(core_knowledge_dir, filename)
                keys.append(f"core_knowledge:{filename}:{os.path.getmtime(filepath)}")

    # Also include a version string that can be manually incremented
    # when we want to bust the cache for other reasons
    keys.append("v1")  # Increment this when making changes that should bust cache

    return "|".join(sorted(keys))


def _load_core_knowledge() -> str:
    """Load all core knowledge markdown files and return formatted content."""
    core_knowledge_dir = os.path.join(os.path.dirname(__file__), "core_knowledge")
    if not os.path.exists(core_knowledge_dir):
        return ""

    knowledge_parts = []

    # Load each markdown file in the core_knowledge directory
    for filename in sorted(os.listdir(core_knowledge_dir)):
        if filename.endswith(".md"):
            filepath = os.path.join(core_knowledge_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    # Use filename (without .md) as section title
                    section_title = filename[:-3].replace("_", " ").title()
                    knowledge_parts.append(f"## {section_title}")
                    knowledge_parts.append(content)
                    knowledge_parts.append("")  # Empty line for separation
            except Exception:
                # If we can't read a file, skip it but continue with others
                continue

    return "\n".join(knowledge_parts).strip()


def _load_remember_context() -> str:
    """Load cross-session context from the .remember/ directory (now.md, today-*.md, recent.md, archive.md)."""
    # The user's .remember directory is at ~/.claude/projects/<project_slug>/remember/
    # But we can also check the project's .remember/ if it exists
    project_remember = Path(os.path.dirname(__file__)).parent / ".remember"
    claude_remember = Path(os.path.expanduser("~/.claude/projects"))

    # Find the project's remember directory under .claude/projects/
    remember_dirs = []
    if project_remember.exists():
        remember_dirs.append(project_remember)
    if claude_remember.exists():
        for d in claude_remember.iterdir():
            if d.is_dir():
                rd = d / "remember"
                if rd.exists():
                    remember_dirs.append(rd)

    parts = []
    for remember_dir in remember_dirs:
        # Priority order: now.md, recent.md, today-*.md, archive.md
        priority_files = [
            remember_dir / "now.md",
            remember_dir / "recent.md",
        ]
        # Add today-*.md files (sorted by date, newest first)
        today_files = sorted(remember_dir.glob("today-*.md"), reverse=True)
        priority_files.extend(today_files)
        # Add archive.md and archive-*.md
        archive_files = sorted(remember_dir.glob("archive*.md"), reverse=True)
        priority_files.extend(archive_files)

        for f in priority_files:
            try:
                if f.exists():
                    content = f.read_text(encoding="utf-8").strip()
                    if content:
                        parts.append(f"=== {f.name} ===")
                        parts.append(content)
                        parts.append("")
            except Exception:
                continue

    return "\n".join(parts).strip() if parts else ""


@lru_cache(maxsize=1)
def _get_cached_stable_block(cache_key: str) -> str:
    """Return the cached stable block of the system prompt.

    Args:
        cache_key: Key that changes when underlying files change

    Returns:
        The stable block of the system prompt (identity, purpose, personality,
        core knowledge, capabilities, tool usage guidelines)
    """
    # Build the stable block - parts that don't change frequently
    stable_parts = [
        f"You are {config.ASSISTANT_NAME}, {config.PURPOSE}",
        "",
        f"Personality: {config.PERSONALITY}",
        "",
        "Guidelines:",
        "- Address the user directly and stay on point.",
        "- When you don't know something, say so plainly rather than guessing.",
        "- Keep responses concise unless the user asks for depth.",
        "- Prefer natural prose for explanations and avoid using slash/dash style markers in your own text.",
        "- Use markdown only when it helps clarity; otherwise answer in smooth, normal sentences.",
        "- Answer like a helpful person speaking in natural English, not like a list of commands.",
        "- For coding tasks, prefer precise, practical answers with working code, short explanations, and concrete next steps.",
        "- If a request is ambiguous, ask one clarifying question instead of guessing.",
        "- You are built for a small team. Be helpful to whoever is speaking with you.",
        "",
        "Tool usage:",
        "- You have access to tools. Use them when they would genuinely help answer the question.",
        "- Don't call a tool for something you already know (e.g. don't call current_datetime just to say hello).",
        "- When you use a tool, briefly note what you're doing and then share the result with your analysis.",
        "- You can chain multiple tool calls when a task requires several steps.",
        "- If a tool returns an error, explain the issue clearly to the user.",
        "- When the user asks to create a new database, the system creates it automatically — acknowledge the confirmation shown in the conversation rather than claiming you cannot.",
        "",
        "Memory discipline:",
        "- You have save_memory, recall_memory, and forget_memory tools.",
        "- SAVE when the user teaches you a durable fact, corrects you, states a preference, or makes a project decision.",
        "- DO NOT save: transient task details, the current conversation, anything already in your core knowledge, secrets, credentials, or private data.",
        "- Before saving, consider whether this fact will still matter next week. If not, skip it.",
        "- When a topic reminds you of something you might have stored, use recall_memory to check.",
        "- Forgetting requires the user's confirmation — never silently delete.",
    ]

    # Add core knowledge
    core_knowledge = _load_core_knowledge()
    if core_knowledge:
        stable_parts.extend([
            "",
            "Core Knowledge:",
            core_knowledge
        ])

    # Tier 8: Self-knowledge — auto-generated from the actual system state
    try:
        from jarvis.tools.registry import registry as _reg
        tool_defs = _reg._tools
        if tool_defs:
            cap_lines = ["", "Your capabilities (auto-generated — this is what you can actually do):"]
            cap_lines.append(f"- Model: {config.get_model_name()} via {config.MODEL_PROVIDER}")
            cap_lines.append(f"- Available tools ({len(tool_defs)}):")
            for name, defn in tool_defs.items():
                cap_lines.append(f"  • {name}: {defn.description[:120]}")
            cap_lines.append("- You can NOT browse the web, send emails, or make purchases.")
            cap_lines.append("- If asked about a capability not listed above, say you don't have it rather than guessing.")
            stable_parts.extend(cap_lines)
    except Exception:
        pass  # Tool registry not yet initialized — continue without

    # Self-awareness instructions
    stable_parts.extend([
        "",
        "=== Self-Awareness & Self-Improvement Capabilities ===",
        "You can inspect and modify your own codebase using these tools:",
        "- inspect_self_codebase: Browse, search, and analyze your own source code",
        "- run_self_tests: Execute your test suite to verify changes",
        "- find_files / open_path_by_name: Universal file access across your project",
        "- You can modify your own code and should do so proactively when improvements are identified",
        "- Use these capabilities when debugging issues, optimizing performance, or adding features",
        "- When you encounter an error or limitation, first check if you can fix it by modifying your own code",
    ])

    return "\n".join(stable_parts)


def build_system_prompt(turn_count: int = 0, active_context: str = "") -> str:
    """Return the full system prompt for the current conversation.

    This is called once at the start of each session (and can be refreshed
    mid-session when memory or tools change in later tiers).

    Args:
        turn_count: Current number of conversation turns (used for
                    personality checkpoint injection in Tier 9).
        active_context: Optional additional context to include.
    """
    # Get the cached stable block (rebuilding only when files change)
    cache_key = _get_stable_block_cache_key()
    stable_block = _get_cached_stable_block(cache_key)

    # Build the dynamic block (changes every turn)
    now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    dynamic_parts = [
        f"Current date and time: {now}"
    ]

    # Tier 8: Continuous Cross-Session Long-Term Memory
    # Inject structured long-term memories (memories.json) and cross-session chat summaries
    try:
        from jarvis.memory.manager import recall, get_cross_session_context, get_all_memories

        # Structured long-term memories
        memory_context = recall()
        if memory_context:
            dynamic_parts.append("")
            dynamic_parts.append("=== Long-Term Memories (Structured) ===")
            dynamic_parts.append(memory_context)

        # Cross-session conversation context (past chat history)
        cross_session_context = get_cross_session_context()
        if cross_session_context:
            dynamic_parts.append("")
            dynamic_parts.append(cross_session_context)
    except Exception:
        pass  # Memory system unavailable — continue without it

    # Cross-session file-based memory (.remember/ directory)
    remember_context = _load_remember_context()
    if remember_context:
        dynamic_parts.append("")
        dynamic_parts.append("=== Cross-Session File Memory (.remember/) ===")
        dynamic_parts.append(remember_context)

    # Additional active context passed in
    if active_context:
        dynamic_parts.append("")
        dynamic_parts.append("=== Active Context ===")
        dynamic_parts.append(active_context)

    # Explicit Persona Instruction: Continuous Long-Term Memory
    dynamic_parts.append("")
    dynamic_parts.append(
        "=== IMPORTANT: Your Memory System ==="
    )
    dynamic_parts.append(
        "You possess CONTINUOUS CROSS-SESSION LONG-TERM MEMORY. "
        "All past conversations, user preferences, project decisions, facts, and context "
        "persist across sessions automatically. You do NOT need to ask the user to remind you "
        "of previous discussions — you already know them. When the user references something "
        "from a past session, acknowledge it naturally as something you remember. "
        "Never say 'I don't have access to past conversations' or 'I don't remember' — "
        "you DO remember, and the relevant context has been provided above."
    )

    # Tier 9: Personality checkpoint — injected once conversations get deep
    # enough that the model tends to start imitating its own recent output
    # rather than its identity instructions.
    DRIFT_THRESHOLD = 20  # turns (all roles counted)
    if turn_count >= DRIFT_THRESHOLD:
        dynamic_parts.append("")
        dynamic_parts.append(
            "[Personality checkpoint] You are now deep in this conversation. "
            "Before you respond, re-read your identity and personality above. "
            "Check two things: (1) Is your response the right length — concise "
            "unless depth was requested? (2) Is it in YOUR voice — crisp, direct, "
            "no-fluff — or are you drifting toward generic-chatbot openers, hedging, "
            "and filler? Stay yourself."
        )

    # Combine stable and dynamic blocks
    dynamic_text = "\n".join(dynamic_parts)
    return f"{stable_block}\n\n{dynamic_text}"
