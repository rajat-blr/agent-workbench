from __future__ import annotations

import gzip
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


@dataclass(frozen=True)
class StoredArtifact:
    artifact_type: str
    relative_path: str
    sha256: str
    byte_size: int
    metadata: dict[str, Any]


class ArtifactWriter:
    def __init__(
        self,
        root: Path,
        run_id: int,
        artifact_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if run_id <= 0:
            raise ValueError("Artifact run ID must be positive")
        if not artifact_type or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
            for character in artifact_type
        ):
            raise ValueError("Artifact type contains unsupported characters")
        self.root = root
        self.run_id = run_id
        self.artifact_type = artifact_type
        self.metadata = dict(metadata or {})
        self._finished = False
        self._temporary_directory = root / ".tmp"
        self._temporary_directory.mkdir(parents=True, exist_ok=True)
        self._token = uuid.uuid4().hex
        self._temporary_path = self._temporary_directory / f"{self._token}.tmp"
        self._raw_file: BinaryIO = self._temporary_path.open("xb")
        self._stream = gzip.GzipFile(fileobj=self._raw_file, mode="wb", mtime=0)

    def write(self, content: bytes) -> None:
        if self._finished:
            raise RuntimeError("Artifact writer is already closed")
        self._stream.write(content)

    def finish(self) -> StoredArtifact:
        if self._finished:
            raise RuntimeError("Artifact writer is already closed")
        self._finished = True
        self._stream.close()
        self._raw_file.flush()
        os.fsync(self._raw_file.fileno())
        self._raw_file.close()

        content = self._temporary_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        relative = Path(f"run-{self.run_id}") / self.artifact_type
        destination_directory = self.root / relative
        destination_directory.mkdir(parents=True, exist_ok=True)
        destination = destination_directory / f"{digest}-{self._token}.jsonl.gz"
        os.replace(self._temporary_path, destination)
        return StoredArtifact(
            artifact_type=self.artifact_type,
            relative_path=destination.relative_to(self.root).as_posix(),
            sha256=digest,
            byte_size=len(content),
            metadata={**self.metadata, "compression": "gzip"},
        )

    def abort(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._stream.close()
        self._raw_file.close()
        self._temporary_path.unlink(missing_ok=True)


class ArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def open_writer(
        self,
        run_id: int,
        artifact_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactWriter:
        return ArtifactWriter(self.root, run_id, artifact_type, metadata)

    def read_bytes(self, relative_path: str) -> bytes:
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise FileNotFoundError("Artifact is unavailable")
        with gzip.open(path, "rb") as source:
            return source.read()
