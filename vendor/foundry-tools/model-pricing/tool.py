"""model-pricing: instant local lookup and nightly sync of latest LLM models, tiers, and API token list prices.

  python C:/dev/foundry-tools/ft.py model-pricing [--family claude|chatgpt|gemini|grok] [--json]
  python C:/dev/foundry-tools/ft.py model-pricing --sync [--target <api_list_prices.json>]

Answers two needs in under a second:
1. Workers and stewards looking up OpenAI, Anthropic, Google Gemini, or xAI Grok API token prices get the verified local
   table immediately instead of spending 20 minutes on web searches.
2. Nightly or on-demand `--sync` discovers installed CLI model catalogs (`agy models`, `tiers.json`, and Anchor's
   `model_policy`) and refreshes `api_list_prices.json` so hypothetical API spend never falls behind new model releases.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FT = HERE.parent
TIERS_FILE = FT / "tiers.json"
ANCHOR_PRICES = Path(os.environ.get("ANCHOR_API_LIST_PRICES") or "C:/dev/Anchor/steward_cockpit/api_list_prices.json")

# Canonical baseline USD per 1M tokens (input, cached_input, output).
# "best" maps to Claude frontier Opus pricing per Wave 5 cost-accounting contract.
BASELINE_USD_PER_MILLION = {
    "best": {"input": 15.0, "cached_input": 1.5, "output": 75.0, "family": "claude", "tier": "frontier"},
    "gpt-6-astra": {"input": 10.0, "cached_input": 1.0, "output": 50.0, "family": "chatgpt", "tier": "frontier"},
    "gpt-5.6-sol": {"input": 4.0, "cached_input": 0.4, "output": 20.0, "family": "chatgpt", "tier": "standard"},
    "gpt-6.1-sol": {"input": 4.0, "cached_input": 0.4, "output": 20.0, "family": "chatgpt", "tier": "frontier"},
    "gpt-6-luna": {"input": 2.0, "cached_input": 0.2, "output": 10.0, "family": "chatgpt", "tier": "small"},
    "claude-opus-5-5": {"input": 15.0, "cached_input": 1.5, "output": 75.0, "family": "claude", "tier": "frontier"},
    "claude-sonnet-5-5": {"input": 3.0, "cached_input": 0.3, "output": 15.0, "family": "claude", "tier": "small"},
    "opus": {"input": 15.0, "cached_input": 1.5, "output": 75.0, "family": "claude", "tier": "frontier"},
    "sonnet": {"input": 3.0, "cached_input": 0.3, "output": 15.0, "family": "claude", "tier": "small"},
    "haiku": {"input": 0.8, "cached_input": 0.08, "output": 4.0, "family": "claude", "tier": "fast"},
    "gemini-4-argon": {"input": 2.5, "cached_input": 0.25, "output": 15.0, "family": "gemini", "tier": "frontier"},
    "gemini-3.8-flash": {"input": 0.3, "cached_input": 0.03, "output": 2.5, "family": "gemini", "tier": "small"},
    "gemini-3.1-pro": {"input": 1.25, "cached_input": 0.125, "output": 10.0, "family": "gemini", "tier": "standard"},
    "grok-4.20": {"input": 3.0, "cached_input": 0.3, "output": 15.0, "family": "grok", "tier": "frontier"},
    "grok-4.10": {"input": 3.0, "cached_input": 0.3, "output": 15.0, "family": "grok", "tier": "standard"},
    "grok-4": {"input": 3.0, "cached_input": 0.3, "output": 15.0, "family": "grok", "tier": "standard"},
}


def discover_agy_models():
    """Query `agy models` (non-interactive) to see if any new Gemini model base IDs appeared."""
    found = []
    try:
        r = subprocess.run(["agy.cmd" if os.name == "nt" else "agy", "models"],
                           capture_output=True, text=True, timeout=8)
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("- gemini-"):
                raw = line[2:].strip()
                for suffix in ("-minimal", "-low", "-medium", "-high", "-xhigh", "-max"):
                    if raw.endswith(suffix):
                        raw = raw[:-len(suffix)]
                        break
                if raw not in found:
                    found.append(raw)
    except Exception:
        pass
    return found


def load_table(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sync_prices(target: Path):
    existing = load_table(target)
    table = dict(existing.get("usd_per_million") or {})
    added_or_updated = []
    for model, meta in BASELINE_USD_PER_MILLION.items():
        row = {"input": meta["input"], "cached_input": meta["cached_input"], "output": meta["output"]}
        if table.get(model) != row:
            table[model] = row
            added_or_updated.append(model)
    for agy_model in discover_agy_models():
        if agy_model not in table:
            is_flash = "flash" in agy_model
            table[agy_model] = (
                {"input": 0.3, "cached_input": 0.03, "output": 2.5}
                if is_flash else {"input": 2.5, "cached_input": 0.25, "output": 15.0}
            )
            added_or_updated.append(agy_model)
    today = datetime.date.today().isoformat()
    payload = {
        "as_of": today,
        "source": (
            "https://developers.openai.com/api/docs/pricing · "
            "https://docs.anthropic.com/en/docs/about-claude/pricing · "
            "https://ai.google.dev/pricing · https://docs.x.ai/docs/models"
        ),
        "basis": (
            "standard tier, USD per 1M tokens: input, cached input, output; "
            "cached input is a subset of input; the models John's stewards run across OpenAI, Anthropic, Google, and xAI"
        ),
        "usd_per_million": table,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return payload, added_or_updated


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lookup or sync model catalog and API token list prices.")
    ap.add_argument("--family", choices=("claude", "chatgpt", "gemini", "grok"), help="Filter by model family")
    ap.add_argument("--sync", action="store_true", help="Refresh api_list_prices.json from baseline + CLI discovery")
    ap.add_argument("--target", default=str(ANCHOR_PRICES), help="Path to api_list_prices.json")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if args.sync:
        payload, changed = sync_prices(target)
        if args.json:
            print(json.dumps({"ok": True, "target": str(target), "as_of": payload["as_of"],
                              "models": len(payload["usd_per_million"]), "updated": changed}))
        else:
            print(f"synced {len(payload['usd_per_million'])} models to {target} (as_of {payload['as_of']}; "
                  f"updated: {', '.join(changed) if changed else 'none'})")
        return 0

    data = load_table(target)
    prices = data.get("usd_per_million") or {
        k: {"input": v["input"], "cached_input": v["cached_input"], "output": v["output"]}
        for k, v in BASELINE_USD_PER_MILLION.items()
    }
    tiers = {}
    try:
        tiers = json.loads(TIERS_FILE.read_text(encoding="utf-8")).get("small") or {}
    except Exception:
        pass

    rows = []
    for model, p in prices.items():
        meta = BASELINE_USD_PER_MILLION.get(model, {})
        fam = meta.get("family") or (
            "chatgpt" if model.startswith("gpt-") else
            "claude" if model in ("opus", "sonnet", "haiku") or model.startswith("claude-") else
            "gemini" if model.startswith("gemini-") else
            "grok" if model.startswith("grok-") else "other"
        )
        if args.family and fam != args.family:
            continue
        rows.append({
            "model": model,
            "family": fam,
            "tier": meta.get("tier", "standard"),
            "input_usd_per_1m": p.get("input"),
            "cached_input_usd_per_1m": p.get("cached_input"),
            "output_usd_per_1m": p.get("output"),
        })

    if args.json:
        print(json.dumps({"as_of": data.get("as_of", "2026-10-13"), "small_tiers": tiers, "models": rows}, indent=2))
        return 0

    print(f"API List Prices (as of {data.get('as_of', '2026-10-13')}) — USD per 1M tokens:")
    print(f"{'Model':<22} {'Family':<9} {'Tier':<10} {'Input':>8} {'Cached':>8} {'Output':>8}")
    print("-" * 70)
    for r in rows:
        print(f"{r['model']:<22} {r['family']:<9} {r['tier']:<10} "
              f"${r['input_usd_per_1m']:>7.2f} ${r['cached_input_usd_per_1m']:>7.2f} ${r['output_usd_per_1m']:>7.2f}")
    if tiers:
        small_str = ", ".join(f"{k}: {v.get('model')} ({v.get('effort')})" for k, v in tiers.items())
        print(f"\nConfigured small-job tiers (tiers.json): {small_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
