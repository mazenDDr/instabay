"""NFR-03, NFR-06: HUMAN run on gpu-box; pin the candidate caption model before inference."""

import hashlib
import importlib
import json
from pathlib import Path

REPO = "Qwen/Qwen3-8B"
REVISION = "b968826d9c46dd6066d109eabc6255188de91218"  # pragma: allowlist secret - public revision


def main() -> None:
    path = Path("data/caption-model-8b")
    importlib.import_module("huggingface_hub").snapshot_download(
        repo_id=REPO,
        revision=REVISION,
        local_dir=path,
        allow_patterns=["*.json", "*.safetensors", "*.model", "tokenizer*", "LICENSE"],
        max_workers=2,
    )
    files = []
    for file in sorted(path.rglob("*")):
        if file.is_file() and ".cache" not in file.parts:
            with file.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            files.append({"uri": file.as_posix(), "sha256": sha, "bytes": file.stat().st_size})
    manifest = {
        "repo": REPO,
        "revision": REVISION,
        "files": files,
        "quantization": "NF4 double quantization, bf16 compute; loaded locally",
        "license": "Apache-2.0",
    }
    Path("outputs/caption-model-8b.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Pinned caption model downloaded and hashed", flush=True)


if __name__ == "__main__":
    main()
