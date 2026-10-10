from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./agent_workbench.db"
    artifact_directory: str | None = None
    eval_worktree_directory: str | None = None
    eval_repository_directory: str | None = None
    codex_command: str = "codex"
    codex_model: str | None = None
    agent_sandbox: str = "workspace-write"
    codex_skip_git_repo_check: bool = False
    agent_timeout_seconds: int = 3600
    local_auth_token: str = ""
    allowed_origins: str = (
        "http://127.0.0.1:5173,http://localhost:5173,workbench://app,null,file://"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        ]

    def prepare_database_directory(self) -> None:
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite+aiosqlite database URLs are supported")
        raw_path = self.database_url.removeprefix(prefix)
        if raw_path != ":memory:":
            Path(raw_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )

    @property
    def resolved_artifact_directory(self) -> Path:
        if self.artifact_directory:
            return Path(self.artifact_directory).expanduser().resolve()
        raw_path = self.database_url.removeprefix("sqlite+aiosqlite:///")
        if raw_path == ":memory:":
            return Path("./artifacts").resolve()
        return Path(raw_path).expanduser().resolve().parent / "artifacts"

    @property
    def resolved_eval_repository_directory(self) -> Path:
        if self.eval_repository_directory:
            return Path(self.eval_repository_directory).expanduser().resolve()
        return self.resolved_artifact_directory.parent / "eval-repositories"

    @property
    def resolved_eval_worktree_directory(self) -> Path:
        if self.eval_worktree_directory:
            return Path(self.eval_worktree_directory).expanduser().resolve()
        raw_path = self.database_url.removeprefix("sqlite+aiosqlite:///")
        if raw_path == ":memory:":
            return Path("./eval-worktrees").resolve()
        return Path(raw_path).expanduser().resolve().parent / "eval-worktrees"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
