import ast
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def test_prd_ignore_patterns_keep_documents_private_without_hiding_source():
    ignored = {
        "docs/evals-mode-prd.md",
        "PRD.md",
        "docs/PrD-new-feature.MD",
        "docs/PRD_future.txt",
        "docs/evals_PRD.docx",
        "docs/evals.PRD.PDF",
        "docs/nested/product-prd.md",
    }
    visible = {
        "backend/prd_parser.py",
        "frontend/src/PRD-button.tsx",
        "docs/surprdise.md",
        "docs/prdnotes.md",
        "docs/PRD-guide.py",
        "docs/evals-prd.json",
        "docs/README.md",
        "docs/rpc-handlers.md",
    }
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=ROOT,
        input="\0".join(sorted(ignored | visible)).encode() + b"\0",
        capture_output=True,
        check=False,
    )
    assert result.returncode in {0, 1}, result.stderr.decode()
    assert set(result.stdout.decode().rstrip("\0").split("\0")) == ignored


def test_backend_metadata_lockfile_and_lint_policy_are_consistent():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    lock = tomllib.loads((BACKEND / "uv.lock").read_text())
    assert project["project"]["name"] == "agent-workbench-backend"
    assert "Codex chats" in project["project"]["description"]
    assert project["project"]["requires-python"] == lock["requires-python"] == ">=3.14"
    assert [
        package["name"]
        for package in lock["package"]
        if package["source"] == {"virtual": "."}
    ] == ["agent-workbench-backend"]
    lint = project["tool"]["ruff"]["lint"]
    assert {"B", "ASYNC", "UP", "SIM", "S", "BLE", "RUF100"} <= set(lint["select"])
    assert not lint.get("ignore")
    assert project["tool"]["ruff"]["target-version"] == "py313"


def test_production_multi_exception_handlers_keep_parentheses():
    files = [
        *BACKEND.glob("*.py"),
        *(BACKEND / "evals").glob("*.py"),
        *(BACKEND / "rpc_handlers").glob("*.py"),
    ]
    for path in files:
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
                assert ast.get_source_segment(source, node.type).startswith("("), (
                    path.name,
                    node.lineno,
                )
