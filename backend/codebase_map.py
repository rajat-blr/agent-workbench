import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

MAP_OPEN = "<agent-workbench-map>"
MAP_CLOSE = "</agent-workbench-map>"
MAP_PATTERN = re.compile(
    rf"{re.escape(MAP_OPEN)}\s*(.*?)\s*{re.escape(MAP_CLOSE)}", re.DOTALL
)

MAP_INSTRUCTIONS = f"""

Agent Workbench codebase map request: Explain the architecture in your normal answer.
Then append exactly one {MAP_OPEN}...{MAP_CLOSE} block containing only JSON:
{{"nodes":[{{"id":"short-id","label":"Component","summary":"What it does","files":["relative/path.py"]}}],"edges":[{{"source":"short-id","target":"other-id","label":"How they interact"}}]}}
Use at most 10 meaningful components and 18 relationships. Include only files you
actually inspected. File paths must be relative to the workspace. Do not invent
components or relationships. The JSON block is for the app, not the user-facing answer.
"""


class MapNode(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=300)
    files: list[str] = Field(default_factory=list, max_length=8)


class MapEdge(BaseModel):
    source: str
    target: str
    label: str = Field(min_length=1, max_length=100)


class CodebaseMap(BaseModel):
    nodes: list[MapNode] = Field(min_length=1, max_length=10)
    edges: list[MapEdge] = Field(default_factory=list, max_length=18)


def extract_codebase_map(content: str, workspace_path: str) -> tuple[str, dict | None]:
    match = MAP_PATTERN.search(content)
    if not match:
        return content, None
    visible = (content[: match.start()] + content[match.end() :]).strip()
    try:
        map_data = CodebaseMap.model_validate(json.loads(match.group(1)))
    except (ValueError, ValidationError):
        return visible, None

    node_ids = [node.id for node in map_data.nodes]
    if len(set(node_ids)) != len(node_ids):
        return visible, None
    if any(
        edge.source not in node_ids or edge.target not in node_ids
        for edge in map_data.edges
    ):
        return visible, None

    workspace = Path(workspace_path).resolve()
    for node in map_data.nodes:
        safe_files: list[str] = []
        for filename in node.files:
            file_path = (workspace / filename).resolve()
            if file_path.is_file() and file_path.is_relative_to(workspace):
                safe_files.append(str(file_path.relative_to(workspace)))
        node.files = safe_files
    return visible, map_data.model_dump()
