#!/usr/bin/env python3
"""Fill curated-data gaps for CUDA/ROCm versions that appear in the wheel matrix.

For every accelerator version in data/torch_matrix.json that the curated files
don't cover yet, look the facts up from machine-readable vendor sources:

- CUDA minimum Linux driver: the ``nvidia_driver`` entry of NVIDIA's redist
  manifest (redistrib_<ver>.json) for the toolkit's first release. Toolkits
  that no longer bundle a driver (13.4+) only name a driver branch, so the
  entry is recorded as null, as it is for Windows.
- CUDA compute capabilities: ``nvcc --list-gpu-arch`` from that release's
  cuda_nvcc redist archive. Needs Linux x86_64 (the CI runner).
- ROCm gfx targets: the per-release compatibility matrix on rocm.docs.amd.com.

Existing entries are never changed, and new ones are inserted as text so the
files keep their hand-maintained layout. Exits 1 if any gap is left unfilled.
"""

from __future__ import annotations

import io
import json
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"

CUDA_REDIST_URL = "https://developer.download.nvidia.com/compute/cuda/redist/"
ROCM_MATRIX_URL = "https://rocm.docs.amd.com/en/docs-{ver}/compatibility/compatibility-matrix.html"

_USER_AGENT = "torch-compat-data-sync (+https://github.com/DanielHou315/torch-compat)"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def find_missing(matrix: dict, drivers: dict, sms: dict, rocm: dict) -> tuple[list, list, list]:
    """Return (cuda versions missing a driver, missing SMs, ROCm versions missing)."""
    combos = matrix["combos"]
    cuda = sorted({c["accel_ver"] for c in combos if c["accel"] == "cuda"}, key=_version_key)
    missing_driver = [v for v in cuda if v not in drivers["linux"]]
    missing_sm = [v for v in cuda if v not in sms["support"]]
    missing_rocm = sorted(
        {
            v
            for v in (c["accel_ver"] for c in combos if c["accel"] == "rocm")
            if v not in rocm["support"] and _minor(v) not in rocm["support"]
        },
        key=_version_key,
    )
    return missing_driver, missing_sm, missing_rocm


def _version_key(ver: str) -> tuple[int, ...]:
    return tuple(int(p) for p in ver.split("."))


def _minor(ver: str) -> str:
    return ".".join(ver.split(".")[:2])


# --- CUDA ------------------------------------------------------------------


def first_redistrib(index_html: str, cuda_ver: str) -> str | None:
    """Name of the earliest ``redistrib_<cuda_ver>.<patch>.json`` in the index."""
    pattern = re.compile(rf"redistrib_{re.escape(cuda_ver)}\.(\d+)\.json")
    patches = sorted({int(m.group(1)) for m in pattern.finditer(index_html)})
    return f"redistrib_{cuda_ver}.{patches[0]}.json" if patches else None


def parse_gpu_arch_list(output: str) -> list[str]:
    """``nvcc --list-gpu-arch`` output -> compute capabilities like ``"8.6"``.

    Architecture-specific (``compute_90a``) and family (``compute_100f``)
    variants are folded into their base capability.
    """
    caps = set()
    for m in re.finditer(r"\bcompute_(\d+)(?:[af])?\b", output):
        digits = m.group(1)
        caps.add(f"{digits[:-1]}.{digits[-1]}")
    return sorted(caps, key=_version_key)


def cuda_compute_capabilities(manifest: dict) -> list[str]:
    if (platform.system(), platform.machine()) != ("Linux", "x86_64"):
        raise RuntimeError("nvcc --list-gpu-arch needs Linux x86_64")
    rel = manifest["cuda_nvcc"]["linux-x86_64"]["relative_path"]
    archive = _fetch(CUDA_REDIST_URL + rel)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as tar:
            tar.extractall(tmp, filter="data")
        nvcc = next(Path(tmp).glob("*/bin/nvcc"))
        out = subprocess.run(
            [str(nvcc), "--list-gpu-arch"], capture_output=True, text=True, check=True
        ).stdout
    return parse_gpu_arch_list(out)


# --- ROCm ------------------------------------------------------------------


def parse_gfx_targets(html: str) -> list[str]:
    """gfx targets on a ROCm compatibility-matrix page, in the curated order."""
    targets = set(re.findall(r"\bgfx[0-9a-f]{3,4}\b", html))
    return sorted(targets, key=lambda t: int(t[3:], 16))


def rocm_gfx_targets(rocm_ver: str) -> list[str]:
    full = rocm_ver if rocm_ver.count(".") >= 2 else f"{rocm_ver}.0"
    return parse_gfx_targets(_fetch(ROCM_MATRIX_URL.format(ver=full)).decode())


# --- file editing ----------------------------------------------------------


def insert_entry(text: str, section: str, key: str, value) -> str:
    """Append ``"key": value`` to the ``"section": {...}`` object of a JSON text.

    The curated files keep one entry per line with compact arrays, which
    json.dump can't reproduce, so the new line is spliced in by hand.
    """
    start = text.index(f'"{section}": {{')
    end = text.index("}", start)  # values are strings/arrays, never objects
    last = len(text[:end].rstrip())  # end of the section's last entry
    indent = re.search(r"\n(\s*)\"[^\n]*$", text[:last]).group(1)
    line = f'{indent}"{key}": {json.dumps(value, separators=(", ", ": "))}'
    new_text = f"{text[:last]},\n{line}{text[last:]}"
    json.loads(new_text)  # never write a broken file
    return new_text


def main() -> int:
    paths = {name: DATA / f"{name}.json" for name in ("cuda_drivers", "cuda_sm_support", "rocm_support")}
    texts = {name: p.read_text() for name, p in paths.items()}
    matrix = json.loads((DATA / "torch_matrix.json").read_text())
    missing_driver, missing_sm, missing_rocm = find_missing(
        matrix, *(json.loads(texts[n]) for n in paths)
    )
    if not (missing_driver or missing_sm or missing_rocm):
        print("Curated data covers every accelerator version")
        return 0

    failed = []
    if missing_driver or missing_sm:
        index = _fetch(CUDA_REDIST_URL).decode()
    for ver in sorted(set(missing_driver) | set(missing_sm), key=_version_key):
        try:
            name = first_redistrib(index, ver)
            if not name:
                raise RuntimeError(f"no redist manifest for CUDA {ver}")
            manifest = json.loads(_fetch(CUDA_REDIST_URL + name))
            if ver in missing_sm:
                caps = cuda_compute_capabilities(manifest)
                if not caps:
                    raise RuntimeError("nvcc listed no architectures")
                texts["cuda_sm_support"] = insert_entry(texts["cuda_sm_support"], "support", ver, caps)
                print(f"CUDA {ver}: compute capabilities {', '.join(caps)}")
            if ver in missing_driver:
                driver = manifest.get("nvidia_driver", {}).get("version")
                texts["cuda_drivers"] = insert_entry(texts["cuda_drivers"], "linux", ver, driver)
                if ver not in json.loads(texts["cuda_drivers"])["windows"]:
                    texts["cuda_drivers"] = insert_entry(texts["cuda_drivers"], "windows", ver, None)
                print(f"CUDA {ver}: Linux driver {driver or 'not published (null)'} ({name})")
        except Exception as e:  # noqa: BLE001 -- report every gap, keep going
            print(f"ERROR: CUDA {ver}: {e}", file=sys.stderr)
            failed.append(f"CUDA {ver}")

    for ver in missing_rocm:
        try:
            targets = rocm_gfx_targets(ver)
            if not targets:
                raise RuntimeError("no gfx targets on the compatibility matrix page")
            texts["rocm_support"] = insert_entry(texts["rocm_support"], "support", _minor(ver), targets)
            print(f"ROCm {ver}: {', '.join(targets)}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: ROCm {ver}: {e}", file=sys.stderr)
            failed.append(f"ROCm {ver}")

    for name, p in paths.items():
        if texts[name] != p.read_text():
            p.write_text(texts[name])
            print(f"Wrote {p}")
    if failed:
        print(f"Could not fill: {', '.join(failed)} -- add these by hand", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
