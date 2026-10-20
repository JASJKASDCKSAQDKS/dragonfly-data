"""
Tools: inspect_self_codebase, run_self_tests — self-awareness and self-modification capabilities.

These tools let Jarvis inspect its own codebase structure, read its own source files,
and run integration tests to verify changes. Self-modifications use the existing
write_file/edit_file tools which require user confirmation via the safety gate.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from jarvis import config
from jarvis.tools.registry import tool


def _resolve_project_path(relative_path: str = "") -> Path:
    """Resolve a path relative to the project root."""
    project_root = Path(config.PROJECT_ROOT)
    if relative_path:
        return (project_root / relative_path).resolve()
    return project_root.resolve()


@tool(
    name="inspect_self_codebase",
    description=(
        "Inspect the Jarvis codebase structure. Can list modules, show directory tree, "
        "or return the full source of a specific module. Use this to understand "
        "the codebase before making self-modifications."
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["tree", "modules", "source"],
                "description": "What to return: 'tree' for directory structure, 'modules' for module list, 'source' for full source of a module",
            },
            "module": {
                "type": "string",
                "description": "Module path (e.g., 'jarvis.tools.editor', 'jarvis.brain') when mode is 'source'",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum depth for tree view (default 3)",
                "default": 3,
            },
        },
        "required": ["mode"],
    },
)
def inspect_self_codebase(mode: str, module: str = "", max_depth: int = 3) -> str:
    """Inspect the Jarvis codebase structure or source code."""
    project_root = _resolve_project_path()

    if not project_root.exists():
        return f"[Error] Project root not found: {project_root}"

    if mode == "tree":
        return _get_tree_view(project_root, max_depth)
    elif mode == "modules":
        return _get_modules_list(project_root)
    elif mode == "source":
        if not module:
            return "[Error] Module parameter required when mode is 'source'"
        return _get_module_source(project_root, module)
    else:
        return f"[Error] Unknown mode: {mode}"


def _get_tree_view(root: Path, max_depth: int) -> str:
    """Generate a directory tree view."""
    lines = [f"Project root: {root}\n"]

    def add_tree(dir_path: Path, prefix: str = "", depth: int = 0):
        if depth >= max_depth:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                new_prefix = prefix + ("    " if is_last else "│   ")
                add_tree(entry, new_prefix, depth + 1)

    add_tree(root)
    return "\n".join(lines)


def _get_modules_list(root: Path) -> str:
    """List all Python modules in the jarvis package."""
    jarvis_dir = root / "jarvis"
    if not jarvis_dir.exists():
        return "[Error] jarvis package not found"

    modules = []
    for py_file in jarvis_dir.rglob("*.py"):
        if py_file.name == "__pycache__":
            continue
        rel_path = py_file.relative_to(root)
        module_path = str(rel_path).replace("/", ".").replace("\\", ".")[:-3]  # Remove .py
        modules.append(module_path)

    modules.sort()
    result = ["Jarvis Modules:\n"]
    for m in modules:
        result.append(f"  • {m}")
    return "\n".join(result)


def _get_module_source(root: Path, module: str) -> str:
    """Get the full source code of a module."""
    # Convert module path to file path
    module_path = module.replace(".", "/")
    if not module_path.endswith(".py"):
        module_path += ".py"

    file_path = root / module_path
    if not file_path.exists():
        # Try without .py if it was added
        file_path = root / module_path[:-3] if module_path.endswith(".py") else root / module_path
        if not file_path.exists():
            return f"[Error] Module not found: {module}"

    try:
        content = file_path.read_text(encoding="utf-8")
        return f"Source: {file_path}\n\n```python\n{content}\n```"
    except Exception as e:
        return f"[Error] Failed to read module: {e}"


@tool(
    name="run_self_tests",
    description=(
        "Run the Jarvis integration test suite (test_jarvis_integrity.py) "
        "to verify the system works correctly after modifications. "
        "Returns pass/fail status and output."
    ),
    parameters={
        "type": "object",
        "properties": {
            "test_file": {
                "type": "string",
                "description": "Test file to run (default: tests/test_all_features.py)",
                "default": "tests/test_all_features.py",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 120)",
                "default": 120,
            },
        },
        "required": [],
    },
)
def run_self_tests(test_file: str = "tests/test_all_features.py", timeout: int = 120) -> str:
    """Run the Jarvis integration test suite."""
    project_root = _resolve_project_path()
    test_path = project_root / test_file

    if not test_path.exists():
        return f"[Error] Test file not found: {test_path}"

    try:
        result = subprocess.run(
            ["python", "-m", "pytest", str(test_path), "-v", "--tb=short"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        output = []
        output.append(f"Exit code: {result.returncode}")
        output.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output.append(f"STDERR:\n{result.stderr}")

        status = "PASSED" if result.returncode == 0 else "FAILED"
        output.insert(0, f"=== Test Result: {status} ===\n")

        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"[Error] Tests timed out after {timeout} seconds"
    except Exception as e:
        return f"[Error] Failed to run tests: {e}"