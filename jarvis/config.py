"""
Jarvis configuration — loads settings from environment and provides defaults.

All tunables live here. Nothing else in the codebase hardcodes model names,
temperatures, or token limits.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Project root directory — allows other modules to find the codebase root
PROJECT_ROOT: Path = Path(__file__).parent.parent.resolve()

# Load .env file from project root (if it exists)
load_dotenv()

JARVIS_ENV: str = os.getenv("JARVIS_ENV", "development").strip().lower()
if JARVIS_ENV not in {"development", "production"}:
    raise ValueError("JARVIS_ENV must be either 'development' or 'production'.")


## ---------------------------------------------------------------------------
# Model Provider Selection
# ---------------------------------------------------------------------------
# Supported: "ollama" (local), "gemini" (cloud). Default: ollama.
MODEL_PROVIDER: str = os.getenv("JARVIS_MODEL_PROVIDER", "ollama").strip().lower()

## ---------------------------------------------------------------------------
# Model (Ollama — local)
# ---------------------------------------------------------------------------
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL: str = os.getenv(
    "JARVIS_OLLAMA_MODEL",
    os.getenv("JARVIS_MODEL", "qwen2.5:1.5b"),
)

## ---------------------------------------------------------------------------
# Model (NVIDIA — cloud, optional / legacy)
# ---------------------------------------------------------------------------
NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_NEMOTRON_MODEL: str = os.getenv("NVIDIA_NEMOTRON_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NVIDIA_DEEPSEEK_MODEL: str = os.getenv("NVIDIA_DEEPSEEK_MODEL", "deepseek-ai/deepseek-v4-flash-0731")
MODEL_NAME: str = os.getenv(
    "JARVIS_MODEL",
    OLLAMA_MODEL if MODEL_PROVIDER == "ollama" else "gemini-2.5-flash",
)
MAX_TOKENS: int = int(os.getenv("JARVIS_MAX_TOKENS", "4096"))
NUM_CTX: int = int(os.getenv("JARVIS_NUM_CTX", "8192"))
TEMPERATURE: float = float(os.getenv("JARVIS_TEMPERATURE", "0.3"))

## ---------------------------------------------------------------------------
# Model (Google Gemini — cloud)
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def get_model_name() -> str:
    """Return the active model name for the configured provider."""
    if MODEL_PROVIDER == "ollama":
        return OLLAMA_MODEL or MODEL_NAME
    if MODEL_PROVIDER == "gemini":
        return MODEL_NAME or GEMINI_MODEL
    return MODEL_NAME


def set_model_name(new_model: str, persist: bool = True) -> str:
    """Set active model name and optionally persist to .env file."""
    global MODEL_NAME, OLLAMA_MODEL
    cleaned = new_model.strip()
    if not cleaned:
        return get_model_name()

    MODEL_NAME = cleaned
    os.environ["JARVIS_MODEL"] = cleaned
    if MODEL_PROVIDER == "ollama":
        OLLAMA_MODEL = cleaned
        os.environ["JARVIS_OLLAMA_MODEL"] = cleaned

    if persist:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        try:
            lines = []
            found_model = False
            found_ollama = False
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("JARVIS_MODEL="):
                            lines.append(f"JARVIS_MODEL={cleaned}\n")
                            found_model = True
                        elif line.startswith("JARVIS_OLLAMA_MODEL="):
                            if MODEL_PROVIDER == "ollama":
                                lines.append(f"JARVIS_OLLAMA_MODEL={cleaned}\n")
                                found_ollama = True
                            else:
                                lines.append(line)
                        else:
                            lines.append(line)
            if not found_model:
                lines.append(f"JARVIS_MODEL={cleaned}\n")
            if MODEL_PROVIDER == "ollama" and not found_ollama:
                lines.append(f"JARVIS_OLLAMA_MODEL={cleaned}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
        except Exception:
            pass

    return get_model_name()


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def _load_identity_from_file() -> dict[str, str]:
    """Load identity from identity.md file with fallback to environment variables."""
    identity_path = os.path.join(os.path.dirname(__file__), "identity.md")
    identity = {
        "name": "Jarvis",
        "purpose": "A dependable AI assistant that helps with coding, personal and team growth, and building a business.",
        "personality": "Talk like a smart colleague, not a chatbot. Use contractions, be direct, skip the filler. Never open with cheerleader phrases. Explain like you're talking to a friend at a whiteboard."
    }

    try:
        if os.path.exists(identity_path):
            with open(identity_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Parse simple markdown format
            lines = content.split("\n")
            current_section = None
            section_content = []

            for line in lines:
                line_stripped = line.strip()
                if line_stripped.startswith("# "):
                    # Save previous section
                    if current_section and section_content:
                        identity[current_section] = "\n".join(section_content).strip()
                    # Start new section
                    current_section = line_stripped[2:].lower().replace(" ", "_")
                    section_content = []
                elif line_stripped.startswith("## "):
                    # Save previous section
                    if current_section and section_content:
                        identity[current_section] = "\n".join(section_content).strip()
                    # Start new subsection
                    current_section = line_stripped[3:].lower().replace(" ", "_")
                    section_content = []
                elif line_stripped and not line_stripped.startswith("#"):
                    section_content.append(line)

            # Save last section
            if current_section and section_content:
                identity[current_section] = "\n".join(section_content).strip()

            # Map markdown sections to identity fields
            if "name" in identity:
                identity["name"] = identity["name"]
            if "purpose" in identity:
                identity["purpose"] = identity["purpose"]
            if "personality" in identity:
                identity["personality"] = identity["personality"]

    except Exception:
        # If parsing fails, fall back to environment variables below
        pass

    # Override with environment variables if set (for backward compatibility)
    identity["name"] = os.getenv("JARVIS_NAME", identity["name"])
    identity["purpose"] = os.getenv("JARVIS_PURPOSE", identity["purpose"])
    identity["personality"] = os.getenv("JARVIS_PERSONALITY", identity["personality"])

    return identity


# Load identity (from file with environment variable fallback)
_IDENTITY_DATA = _load_identity_from_file()
ASSISTANT_NAME: str = _IDENTITY_DATA.get("name", "Jarvis")
PERSONALITY: str = _IDENTITY_DATA.get("personality", "")
PURPOSE: str = _IDENTITY_DATA.get("purpose", "")
STYLE: str = _IDENTITY_DATA.get("communication_style", "")
BELIEFS: str = _IDENTITY_DATA.get("core_beliefs", "")

SYSTEM_PROMPT = f"""MANDATORY IDENTITY RULES:
You are {ASSISTANT_NAME}.
Your Purpose: {PURPOSE}
Your Personality: {PERSONALITY}
Your Core Beliefs: {BELIEFS}
Your Communication Style: {STYLE}

CRITICAL HUMAN-LIKE CONSTRAINTS (Strictly Enforced):
- NEVER use "chatbot" formatting. This means: NO excessive bolding, NO overuse of italics, and NO bullet points for simple conversational replies.
- STOP using AI filler phrases: Never start with "Certainly!", "Absolutely!", "I'd be happy to help!", or "I understand."
- NO "Conclusion" paragraphs: Do not summarize your answer at the end or ask "Does that help?" or "Let me know if you need anything else."
- WRITE LIKE A HUMAN: Use contractions (I'm, don't, can't, you'll). Use short, punchy sentences.
- NO la-di-da language: Avoid words like "furthermore," "moreover," or "consequently." Talk like a smart friend at a whiteboard.
- SYMBOL LIMIT: Use plain punctuation. No fancy Unicode symbols or excessive emojis.
- la-di-da: Just answer the question directly. If the user asks a simple question, give a simple, one-sentence answer.
"""

# ---------------------------------------------------------------------------
# Tools (Tier 2)
# ---------------------------------------------------------------------------
TOOL_TIMEOUT: int = int(os.getenv("JARVIS_TOOL_TIMEOUT", "30"))
TOOL_MAX_OUTPUT: int = int(os.getenv("JARVIS_TOOL_MAX_OUTPUT", "4000"))

# ---------------------------------------------------------------------------
# Turn handling
# ---------------------------------------------------------------------------
TURN_TIMEOUT: int = int(os.getenv("JARVIS_TURN_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# Voice (Tier 3)
# ---------------------------------------------------------------------------
DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # "George"
ELEVENLABS_MODEL: str = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
TTS_ENABLED: bool = os.getenv("JARVIS_TTS", "true").lower() == "true"
STT_MODEL: str = os.getenv("DEEPGRAM_MODEL", "nova-3")
AUDIO_SAMPLE_RATE: int = int(os.getenv("JARVIS_AUDIO_RATE", "16000"))
AUDIO_CHANNELS: int = int(os.getenv("JARVIS_AUDIO_CHANNELS", "1"))
PTT_KEY: str = os.getenv("JARVIS_PTT_KEY", "ctrl_r")  # Right Ctrl

# ---------------------------------------------------------------------------
# Memory (Tier 4)
# ---------------------------------------------------------------------------
DATA_DIR: str = os.getenv("JARVIS_DATA_DIR", os.path.expanduser("~/.jarvis"))
MEMORY_DB: str = os.path.join(DATA_DIR, "memory.db")
MEMORY_MAX_CONTEXT: int = int(os.getenv("JARVIS_MEMORY_MAX_CONTEXT", "2000"))
# Maximum number of messages (all roles) kept in the active conversation window.
# Older turns are silently trimmed from the front to prevent unbounded growth.
MAX_CONVERSATION_TURNS: int = int(os.getenv("JARVIS_MAX_CONVERSATION_TURNS", "80"))

# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

# Commands that run_shell_command will refuse to execute.
SHELL_DENYLIST: list[str] = [
    "rm", "rmdir", "sudo", "su",
    "mkfs", "dd", "fdisk", "parted",
    "shutdown", "reboot", "poweroff", "halt",
    "chmod", "chown",
    "mv",          # can be destructive; unlock later via confirmation gate
    "truncate",
    "> /dev",      # prevent device writes
]

# ---------------------------------------------------------------------------
# Authentication & Multi-tenancy
# ---------------------------------------------------------------------------
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
AUTH_COOKIE_NAME: str = os.getenv("AUTH_COOKIE_NAME", "jarvis_access")
REFRESH_COOKIE_NAME: str = os.getenv("REFRESH_COOKIE_NAME", "jarvis_refresh")
AUTH_COOKIE_SECURE: bool = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
AUTH_COOKIE_SAMESITE: str = os.getenv("AUTH_COOKIE_SAMESITE", "lax")
AUTH_COOKIE_DOMAIN: str | None = os.getenv("AUTH_COOKIE_DOMAIN") or None
DEVELOPER_MFA_REQUIRED: bool = os.getenv("DEVELOPER_MFA_REQUIRED", "false").lower() == "true"
DEVELOPER_EMAIL: str = os.getenv("DEVELOPER_EMAIL", "")
DEVELOPER_PASSWORD: str = os.getenv("DEVELOPER_PASSWORD", "")


def _validate_production_config() -> None:
    """Fail startup when production authentication safeguards are disabled."""
    if JARVIS_ENV != "production":
        return

    failures: list[str] = []
    if JWT_SECRET_KEY == "dev-secret-change-in-production" or len(JWT_SECRET_KEY) < 32:
        failures.append("JWT_SECRET_KEY must be at least 32 characters and not the default")
    if DEVELOPER_PASSWORD == "changeme123" or len(DEVELOPER_PASSWORD) < 12:
        failures.append("DEVELOPER_PASSWORD must be at least 12 characters and not the default")
    if not AUTH_COOKIE_SECURE:
        failures.append("AUTH_COOKIE_SECURE must be true")
    if not DEVELOPER_MFA_REQUIRED:
        failures.append("DEVELOPER_MFA_REQUIRED must be true")

    if failures:
        raise ValueError("Invalid production configuration: " + "; ".join(failures))


_validate_production_config()

# Database paths (no hardcoded ~/bar-ai-system paths)
TENANT_DB_DIR: str = os.getenv("TENANT_DB_DIR", os.path.join(DATA_DIR, "tenants"))
TENANT_DB_TEMPLATE: str = os.getenv("TENANT_DB_TEMPLATE", os.path.join(PROJECT_ROOT, "templates", "standard_bar.sql"))
TENANT_REGISTRY_PATH: str = os.getenv("TENANT_REGISTRY_PATH", os.path.join(DATA_DIR, "tenants.json"))
IMPORT_JOBS_PATH: str = os.getenv("IMPORT_JOBS_PATH", os.path.join(DATA_DIR, "import_jobs.json"))
PRIVACY_REQUESTS_PATH: str = os.getenv("PRIVACY_REQUESTS_PATH", os.path.join(DATA_DIR, "privacy_requests.json"))
# Registry for AI-created databases (separate from the tenant registry —
# the two store different shapes and must not share a file).
DB_REGISTRY_PATH: str = os.getenv("DB_REGISTRY_PATH", os.path.join(DATA_DIR, "databases.json"))

# Client portal accounts — the login credentials (username / email / password)
# minted automatically for every business database the app provisions, so the
# owner can sign in to the client interface. Separate file from the DB registry
# because it stores credential material, not just metadata.
CLIENT_ACCOUNTS_PATH: str = os.getenv(
    "CLIENT_ACCOUNTS_PATH", os.path.join(DATA_DIR, "client_accounts.json")
)
# Domain used for the auto-generated client email addresses.
CLIENT_EMAIL_DOMAIN: str = os.getenv("CLIENT_EMAIL_DOMAIN", "clients.seline.example")

# MariaDB connection targets (core databases the panel browses)
DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
DB_NAME: str = os.getenv("DB_NAME", "")
DB_USER: str = os.getenv("DB_USER", "")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
AI_DB_NAME: str = os.getenv("AI_DB_NAME", "")
AI_DB_USER: str = os.getenv("AI_DB_USER", "")
AI_DB_PASSWORD: str = os.getenv("AI_DB_PASSWORD", "")

# Admin DB credentials (for provisioning + browsing every database)
ADMIN_DB_USER: str = os.getenv("ADMIN_DB_USER", "")
ADMIN_DB_PASSWORD: str = os.getenv("ADMIN_DB_PASSWORD", "")
