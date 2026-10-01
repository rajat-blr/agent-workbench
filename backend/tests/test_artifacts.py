import gzip
import hashlib

from artifacts import ArtifactStore


def test_artifact_store_writes_gzip_atomically(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.open_writer(
        7,
        "raw_jsonl",
        {"content_type": "application/x-ndjson"},
    )
    writer.write(b'{"type":"thread.started"}\n')
    writer.write(b'{"type":"turn.completed"}\n')

    artifact = writer.finish()
    stored_path = store.root / artifact.relative_path

    assert stored_path.exists()
    assert artifact.sha256 == hashlib.sha256(stored_path.read_bytes()).hexdigest()
    assert artifact.byte_size == stored_path.stat().st_size
    assert artifact.metadata == {
        "content_type": "application/x-ndjson",
        "compression": "gzip",
    }
    with gzip.open(stored_path, "rb") as stored:
        assert stored.read() == (
            b'{"type":"thread.started"}\n{"type":"turn.completed"}\n'
        )
    assert list((store.root / ".tmp").iterdir()) == []


def test_artifact_writer_abort_removes_temporary_file(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.open_writer(8, "raw_jsonl")
    writer.write(b"partial")

    writer.abort()

    assert list((store.root / ".tmp").iterdir()) == []
