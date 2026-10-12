"""NFR-03: authorized native-preview weights download directly on gpu-box, resume by revision."""

import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

MODEL = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
REVISION = "b8fff7315c768468a5333511427288870b2e9635"  # pragma: allowlist secret - public pin
if __name__ == "__main__":
    root = Path("data/wan-preview")
    snapshot_download(MODEL, revision=REVISION, local_dir=root, max_workers=3)
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".cache" not in path.parts:
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            files.append({"uri": path.as_posix(), "sha256": sha})
    Path("outputs/wan-weights.json").write_text(
        json.dumps({"repo": MODEL, "revision": REVISION, "files": files}, indent=2)
    )
    print("Pinned download complete:", len(files), "files", flush=True)
