import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analysis/build_caption_style_grammar.py"
SPEC = importlib.util.spec_from_file_location("build_caption_style_grammar", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_builds_gold_backed_reusable_grammar():
    grammar = MODULE.build_grammar(ROOT)

    assert grammar["gold_authority"]["sha256"] == "99b11b92d55c40682f630fd4c52072e006c7e0b6494aef367bda175fb9d4af2e"
    assert grammar["gold_authority"]["modified"] is False
    assert grammar["persistence_rules"]["caption_count"] == 113
    assert grammar["persistence_rules"]["interval_semantics"] == "start_inclusive_end_exclusive"
    assert len(grammar["per_caption_or_cluster_evidence"]) == 113
    assert {item["family"] for item in grammar["caption_style_families"]} == {"regular", "bold", "black", "unresolved"}
    assert {item["family"] for item in grammar["animation_families"]} >= {"static", "fade", "slide", "scale", "combination", "bounce_overshoot"}
    assert grammar["unresolved"]["opacity_count"] == 113
    assert grammar["unresolved"]["entry_source_label_count"] > 0
    assert grammar["confidence"]["animation_family"] == 0.3407
    assert json.dumps(grammar, sort_keys=True) == json.dumps(MODULE.build_grammar(ROOT), sort_keys=True)
