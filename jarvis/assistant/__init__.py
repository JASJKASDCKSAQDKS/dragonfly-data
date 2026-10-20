"""
Assistant module for Jarvis.

Provides the scoped AI assistant for clients with allowlisted read-only tools.
Includes conversation management, tool definitions, and API routes.
"""

from jarvis.assistant.tools import ClientAssistantTools
from jarvis.assistant.conversation import AssistantConversationManager
from jarvis.assistant.service import AssistantService
from jarvis.assistant.routes import router as assistant_router

__all__ = [
    "ClientAssistantTools",
    "AssistantConversationManager",
    "AssistantService",
    "assistant_router",
]