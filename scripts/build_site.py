#!/usr/bin/env python3
"""Render the static site into _site/ from data/ + web/."""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DOMAIN = "torch-compat.danielhou.me"


def _load(name: str) -> dict:
    return json.loads((REPO_ROOT / "data" / name).read_text())


def _embed_json(payload) -> str:
    """JSON safe for inlining in a <script> block."""
    return json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")


def _version_key(v: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", v))


def _summarize(combos: list) -> list:
    """One row per stable PyTorch release, newest first, for the static
    quick-reference table and structured data (crawlable without JS)."""
    by_torch: dict = {}
    for c in combos:
        if ".dev" in c["torch"]:
            continue
        row = by_torch.setdefault(
            c["torch"], {"cuda": set(), "rocm": set(), "xpu": False, "python": set()}
        )
        if c["accel"] in ("cuda", "rocm"):
            row[c["accel"]].add(c["accel_ver"])
        elif c["accel"] == "xpu":
            row["xpu"] = True
        row["python"].update(c["python"])
    return [
        {
            "torch": v,
            "cuda": sorted(r["cuda"], key=_version_key),
            "rocm": sorted(r["rocm"], key=_version_key),
            "xpu": r["xpu"],
            "python": sorted(r["python"], key=_version_key),
        }
        for v, r in sorted(by_torch.items(), key=lambda kv: _version_key(kv[0]), reverse=True)
    ]


def _faq(summary: list, cuda_drivers: dict) -> list:
    latest = summary[0]
    linux_drivers = cuda_drivers.get("linux", {})
    # Recent toolkits only name a driver branch, stored as null; quote the
    # newest CUDA version that has an exact minimum.
    driver_cuda = next((v for v in reversed(latest["cuda"]) if linux_drivers.get(v)), None)
    faq = [
        {
            "q": f"Which CUDA versions does PyTorch {latest['torch']} support?",
            "a": f"PyTorch {latest['torch']} ships official wheels for CUDA "
            f"{', '.join(latest['cuda'])}"
            + (f", ROCm {', '.join(latest['rocm'])}" if latest["rocm"] else "")
            + (", Intel XPU" if latest["xpu"] else "")
            + " and CPU.",
        },
        {
            "q": f"Which Python versions does PyTorch {latest['torch']} support?",
            "a": f"PyTorch {latest['torch']} has wheels for Python "
            f"{', '.join(latest['python'])}.",
        },
    ]
    if driver_cuda:
        faq.append({
            "q": "Which NVIDIA driver version do I need for PyTorch?",
            "a": f"It depends on the CUDA version of the wheel. For example, CUDA "
            f"{driver_cuda} needs driver {linux_drivers[driver_cuda]} or newer "
            f"on Linux. Pick a PyTorch version and CUDA version above to see the "
            f"minimum driver for each build.",
        })
    faq += [
        {
            "q": "Does PyTorch support AMD GPUs?",
            "a": "Yes. PyTorch publishes ROCm wheels for Linux x86_64. Select ROCm as "
            "the accelerator above, or pick your GPU, to see which ROCm builds "
            "officially support your card's gfx architecture.",
        },
        {
            "q": "How do I check which CUDA version my PyTorch was built with?",
            "a": "Run python -c \"import torch; print(torch.__version__, "
            "torch.version.cuda, torch.cuda.is_available())\". torch.version.cuda "
            "is the CUDA toolkit the wheel was built with; your driver must be at "
            "least the minimum listed for that version.",
        },
    ]
    return faq


def _structured_data(faq: list, generated_utc: str) -> str:
    url = f"https://{SITE_DOMAIN}/"
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebApplication",
                "name": "PyTorch Compatibility Matrix",
                "url": url,
                "applicationCategory": "DeveloperApplication",
                "operatingSystem": "Linux, Windows, macOS",
                "description": "Find compatible combinations of PyTorch, Python, "
                "CUDA, ROCm and Intel XPU versions, minimum NVIDIA drivers and the "
                "matching pip install command.",
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                "author": {"@type": "Person", "name": "Daniel Hou",
                           "url": "https://github.com/DanielHou315"},
            },
            {
                "@type": "Dataset",
                "name": "PyTorch build compatibility matrix",
                "description": "Every official PyTorch wheel build with its CUDA, "
                "ROCm or XPU version, Python versions, OS and architecture.",
                "url": url,
                "dateModified": generated_utc,
                "license": "https://opensource.org/licenses/MIT",
                "isBasedOn": "https://download.pytorch.org/whl/torch/",
                "creator": {"@type": "Person", "name": "Daniel Hou"},
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {"@type": "Question", "name": q["q"],
                     "acceptedAnswer": {"@type": "Answer", "text": q["a"]}}
                    for q in faq
                ],
            },
        ],
    }
    return _embed_json(data)


def build(output_dir: Path) -> Path:
    matrix = _load("torch_matrix.json")
    dataset = {
        "generated_utc": matrix["generated_utc"],
        "source": matrix["source"],
        "combos": matrix["combos"],
        "cuda_drivers": _load("cuda_drivers.json"),
        "cuda_sm_support": _load("cuda_sm_support.json")["support"],
        "rocm_support": _load("rocm_support.json")["support"],
        "gpus": _load("gpus.json")["gpus"],
    }

    env = Environment(
        loader=FileSystemLoader(REPO_ROOT / "web"),
        autoescape=select_autoescape(["html"]),
    )
    summary = _summarize(matrix["combos"])
    faq = _faq(summary, dataset["cuda_drivers"])
    html = env.get_template("index.html.j2").render(
        dataset_json=_embed_json(dataset),
        generated_utc=matrix["generated_utc"],
        n_combos=len(matrix["combos"]),
        domain=SITE_DOMAIN,
        summary=summary,
        latest=summary[0],
        faq=faq,
        structured_data=_structured_data(faq, matrix["generated_utc"]),
    )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / "index.html").write_text(html)
    (output_dir / "CNAME").write_text(SITE_DOMAIN + "\n")
    (output_dir / ".nojekyll").write_text("")
    (output_dir / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: https://{SITE_DOMAIN}/sitemap.xml\n"
    )
    (output_dir / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>https://{SITE_DOMAIN}/</loc>"
        f"<lastmod>{matrix['generated_utc'][:10]}</lastmod></url>\n"
        "</urlset>\n"
    )
    for asset in (REPO_ROOT / "web").iterdir():
        if asset.suffix != ".j2":
            shutil.copy(asset, output_dir / asset.name)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "_site")
    args = parser.parse_args()
    out = build(args.output)
    print(f"Site built at {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
