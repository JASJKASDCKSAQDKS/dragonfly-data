"""
Jarvis tool system — auto-discovers and registers all tools.

Import this package to ensure every tool module is loaded and registered
in the global registry.
"""

from jarvis.tools.registry import registry, tool  # noqa: F401

# Import tool modules so their @tool-decorated functions self-register.
import jarvis.tools.datetime_tool  # noqa: F401
import jarvis.tools.filesystem     # noqa: F401
import jarvis.tools.shell          # noqa: F401
import jarvis.tools.memory_tools   # noqa: F401  # Tier 7A: assistant-facing memory tools
import jarvis.tools.editor         # noqa: F401  # write_file, edit_file
import jarvis.tools.universal_access  # noqa: F401  # find_files, open_path_by_name
import jarvis.tools.db_tools  # noqa: F401  # create_database, generate_database_ui
