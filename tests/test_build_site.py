"""Smoke tests: the built site contains the dataset and UI scaffolding."""

import json

from build_site import SITE_DOMAIN, build


def test_build_outputs(tmp_path):
    out = build(tmp_path / "_site")

    index = (out / "index.html").read_text()
    assert 'id="dataset"' in index
    assert 'id="f-torch"' in index
    assert 'id="theme-toggle"' in index
    assert "elenacliu" in index  # acknowledgement must stay

    assert (out / "CNAME").read_text().strip() == SITE_DOMAIN
    assert (out / ".nojekyll").exists()
    assert (out / "app.js").exists()
    assert (out / "style.css").exists()
    assert SITE_DOMAIN in (out / "sitemap.xml").read_text()
    assert "Sitemap:" in (out / "robots.txt").read_text()
    assert not (out / "index.html.j2").exists()


def test_seo_content_is_server_rendered(tmp_path):
    out = build(tmp_path / "_site")
    index = (out / "index.html").read_text()
    start = index.index('<script type="application/ld+json">') + len(
        '<script type="application/ld+json">'
    )
    ld = json.loads(index[start:index.index("</script>", start)])
    assert {n["@type"] for n in ld["@graph"]} >= {"WebApplication", "FAQPage"}
    # The version table is in the HTML itself, crawlable without JS.
    assert "<td>2.0.0</td>" in index


def test_embedded_dataset_is_valid_json(tmp_path):
    out = build(tmp_path / "_site")
    index = (out / "index.html").read_text()
    start = index.index('id="dataset" type="application/json">') + len(
        'id="dataset" type="application/json">'
    )
    end = index.index("</script>", start)
    dataset = json.loads(index[start:end].replace("<\\/", "</"))

    assert dataset["combos"], "dataset must contain combos"
    accels = {c["accel"] for c in dataset["combos"]}
    assert {"cuda", "rocm", "xpu", "cpu"} <= accels
    assert dataset["cuda_drivers"]["linux"]["12.1"] == "530.30.02"
    assert "gfx942" in dataset["rocm_support"]["7.0"]


def test_faq_skips_null_driver_entries(tmp_path):
    index = (build(tmp_path / "_site") / "index.html").read_text()
    assert "needs driver None" not in index
