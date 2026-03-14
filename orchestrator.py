"""
orchestrator.py — Autonomous landing page A/B optimization loop.

Runs daily at 6am UTC via GitHub Actions cron. Each run:
  1. HARVEST  — read CTR from GA4, check significance, promote/revert
  2. GENERATE — Claude generates challenger copy (mutation of baseline)
  3. DEPLOY   — update variant-config.json, git commit & push

Usage:
  python orchestrator.py                # full run
  python orchestrator.py --dry-run      # generate challenger, don't deploy
  python orchestrator.py --harvest-only # just pull results
"""

import os
import sys
import json
import math
import logging
import argparse
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import ga4_client

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("orchestrator")

ROOT = Path(__file__).parent
ACTIVE_EXPERIMENT_FILE = ROOT / "data" / "active_experiment.json"
BASELINE_FILE = ROOT / "config" / "baseline.md"
VARIANT_CONFIG_FILE = ROOT / "data" / "variant-config.json"
RESULTS_LOG = ROOT / "results" / "results.log"
RESOURCE_FILE = ROOT / "data" / "resource.md"
LEARNINGS_FILE = ROOT / "results" / "learnings.md"

MIN_VISITORS_PER_ARM = 100
MIN_EXPERIMENT_DAYS = 7
MAX_EXPERIMENT_DAYS = 21
EARLY_KILL_VISITORS = 50
EARLY_KILL_RATIO = 0.5  # Kill if challenger CTR < 50% of baseline

# Factual content that must never change
PROHIBITED_CHANGES = {
    "comparison_homegrown_1": "$10/mo with everything included",
}
PROHIBITED_PATTERNS = [
    # Price must stay accurate
    r"\$(?!10)[0-9]+/mo",  # Any price other than $10/mo in Homegrown context
]


# ─────────────────────────────────────────────
# STATISTICAL SIGNIFICANCE (verbatim from email optimizer)
# ─────────────────────────────────────────────

def two_proportion_z_test(p1, n1, p2, n2):
    """Two-proportion z-test. Returns (z_score, p_value).

    Tests whether p2 > p1 (one-tailed).
    p1, p2 are success rates; n1, n2 are sample sizes.
    """
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool == 0 or p_pool == 1:
        return 0.0, 1.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    if se == 0:
        return 0.0, 1.0
    z = (p2 - p1) / se
    # Approximate one-tailed p-value using normal CDF
    p_value = 0.5 * math.erfc(z / math.sqrt(2))
    return z, p_value


def is_significant(b_clicks, b_views, c_clicks, c_views, alpha=0.05):
    """Check if challenger CTR significantly beats baseline.

    Returns (is_sig, z_score, p_value).
    """
    if b_views == 0 or c_views == 0:
        return False, 0.0, 1.0
    b_rate = b_clicks / b_views
    c_rate = c_clicks / c_views
    z, p_value = two_proportion_z_test(b_rate, b_views, c_rate, c_views)
    return p_value < alpha, z, p_value


# ─────────────────────────────────────────────
# EXPERIMENT MANAGEMENT
# ─────────────────────────────────────────────

def load_active_experiment() -> dict:
    """Load the active experiment from JSON file."""
    if not ACTIVE_EXPERIMENT_FILE.exists():
        return {}
    data = json.loads(ACTIVE_EXPERIMENT_FILE.read_text())
    if not data or not data.get("experiment_id"):
        return {}
    return data


def save_active_experiment(experiment: dict):
    """Save experiment state to JSON file."""
    ACTIVE_EXPERIMENT_FILE.write_text(json.dumps(experiment, indent=2))


def clear_active_experiment():
    """Clear the active experiment."""
    save_active_experiment({})


def experiment_age_days(experiment: dict) -> int:
    """Get the age of an experiment in days."""
    started = experiment.get("started_at", "")
    if not started:
        return 0
    start_date = datetime.fromisoformat(started).date()
    return (date.today() - start_date).days


# ─────────────────────────────────────────────
# AUTO-LEARNINGS LOG (adapted from email optimizer)
# ─────────────────────────────────────────────

def append_learning(experiment_id: str, log_entry: dict):
    """Append experiment results to results/learnings.md."""
    winner = log_entry.get("winner", "unknown")
    b = log_entry.get("baseline", {})
    c = log_entry.get("challenger", {})
    p_value = log_entry.get("p_value", "N/A")
    hypothesis = log_entry.get("hypothesis", "N/A")
    decision = log_entry.get("decision", "unknown")

    entry = f"""
## Experiment {experiment_id} — {date.today()}
**Hypothesis:** {hypothesis}
**Decision:** {decision} | Winner: **{winner}** (p={p_value})
**CTR:** Baseline {b.get('ctr', 0):.1%} ({b.get('cta_clicks', 0)}/{b.get('page_views', 0)}) vs Challenger {c.get('ctr', 0):.1%} ({c.get('cta_clicks', 0)}/{c.get('page_views', 0)})
**Elements changed:** {log_entry.get('elements_changed', 'unknown')}

"""

    LEARNINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LEARNINGS_FILE.exists():
        LEARNINGS_FILE.write_text("# Landing Page Optimizer — Auto-Learnings Log\n\n")

    with open(LEARNINGS_FILE, "a") as f:
        f.write(entry)

    log.info("Appended learning for %s to learnings.md", experiment_id)


# ─────────────────────────────────────────────
# RESULTS LOGGING
# ─────────────────────────────────────────────

def append_results_log(entry: dict):
    """Append a JSONL entry to results/results.log."""
    RESULTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def save_experiment_record(experiment_id: str, record: dict):
    """Save full experiment record to results/experiments/."""
    exp_dir = ROOT / "results" / "experiments"
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / f"{experiment_id}.json").write_text(json.dumps(record, indent=2))


def get_recent_experiments(n: int = 20) -> str:
    """Get last N experiment results from results.log."""
    if not RESULTS_LOG.exists():
        return ""
    lines = RESULTS_LOG.read_text().strip().split("\n")
    return "\n".join(lines[-n:])


# ─────────────────────────────────────────────
# PHASE 1: HARVEST
# ─────────────────────────────────────────────

def phase_harvest() -> str:
    """Check active experiment results and decide: promote, revert, or keep running.

    Returns a summary string for the generate phase.
    """
    experiment = load_active_experiment()
    if not experiment or not experiment.get("experiment_id"):
        log.info("No active experiment. Skipping harvest.")
        return "No active experiment — ready to generate first challenger."

    exp_id = experiment["experiment_id"]
    age = experiment_age_days(experiment)
    start_date = experiment.get("started_at", date.today().isoformat())

    log.info("Active experiment: %s (age: %d days)", exp_id, age)

    # Get metrics from GA4
    try:
        metrics = ga4_client.get_variant_metrics(start_date)
    except Exception as e:
        log.error("GA4 query failed: %s", e)
        return f"GA4 query failed ({e}). Keeping experiment {exp_id} running."

    b = metrics.get("baseline", {"page_views": 0, "cta_clicks": 0, "ctr": 0})
    c = metrics.get("challenger", {"page_views": 0, "cta_clicks": 0, "ctr": 0})

    b_views = b["page_views"]
    c_views = c["page_views"]
    b_clicks = b["cta_clicks"]
    c_clicks = c["cta_clicks"]

    log.info(
        "Results — Baseline: %d views, %d clicks (%.1f%%) | "
        "Challenger: %d views, %d clicks (%.1f%%)",
        b_views, b_clicks, b["ctr"] * 100,
        c_views, c_clicks, c["ctr"] * 100,
    )

    # Decision logic
    decision = None
    winner = None

    # Early kill: challenger performing terribly after 50+ visitors
    if c_views >= EARLY_KILL_VISITORS and b_views >= EARLY_KILL_VISITORS:
        if b["ctr"] > 0 and c["ctr"] < b["ctr"] * EARLY_KILL_RATIO:
            decision = "early_kill"
            winner = "baseline"
            log.warning(
                "EARLY KILL: Challenger CTR %.1f%% < 50%% of baseline %.1f%%",
                c["ctr"] * 100, b["ctr"] * 100,
            )

    if decision is None:
        # Not enough data yet
        if b_views < MIN_VISITORS_PER_ARM or c_views < MIN_VISITORS_PER_ARM:
            if age < MAX_EXPERIMENT_DAYS:
                decision = "keep_running"
                log.info(
                    "Insufficient data (%d/%d baseline, %d/%d challenger). "
                    "Keeping experiment running (day %d/%d).",
                    b_views, MIN_VISITORS_PER_ARM,
                    c_views, MIN_VISITORS_PER_ARM,
                    age, MAX_EXPERIMENT_DAYS,
                )
            else:
                decision = "timeout_revert"
                winner = "baseline"
                log.info(
                    "Experiment timed out at %d days with insufficient data. "
                    "Reverting to baseline.", age,
                )

    if decision is None:
        # Enough data — run significance test
        sig, z, p_value = is_significant(b_clicks, b_views, c_clicks, c_views)
        if sig:
            decision = "promote"
            winner = "challenger"
            log.info("WINNER: Challenger (z=%.2f, p=%.4f). Promoting.", z, p_value)
        elif age >= MIN_EXPERIMENT_DAYS:
            decision = "no_significance"
            winner = "baseline"
            log.info(
                "No significance after %d days (z=%.2f, p=%.4f). "
                "Keeping baseline.", age, z, p_value,
            )
        else:
            decision = "keep_running"
            log.info(
                "Not yet significant (z=%.2f, p=%.4f) and only %d days old. "
                "Keep running.", z, p_value, age,
            )

    if decision == "keep_running":
        return (
            f"Experiment {exp_id} still running (day {age}). "
            f"Baseline: {b_views} views, {b_clicks} clicks ({b['ctr']:.1%}). "
            f"Challenger: {c_views} views, {c_clicks} clicks ({c['ctr']:.1%})."
        )

    # Experiment is done — log results
    _, z_final, p_final = is_significant(b_clicks, b_views, c_clicks, c_views)

    log_entry = {
        "experiment_id": exp_id,
        "date": date.today().isoformat(),
        "age_days": age,
        "decision": decision,
        "winner": winner,
        "p_value": round(p_final, 4),
        "z_score": round(z_final, 2),
        "baseline": b,
        "challenger": c,
        "hypothesis": experiment.get("hypothesis", ""),
        "elements_changed": experiment.get("elements_changed", ""),
    }

    append_results_log(log_entry)
    save_experiment_record(exp_id, {
        "log_entry": log_entry,
        "experiment_config": experiment,
    })
    append_learning(exp_id, log_entry)

    # Promote or revert
    if winner == "challenger":
        _promote_challenger(experiment)
        summary = (
            f"Experiment {exp_id} PROMOTED challenger. "
            f"CTR improved: {b['ctr']:.1%} → {c['ctr']:.1%} (p={p_final:.4f})"
        )
    else:
        summary = (
            f"Experiment {exp_id} reverted to baseline ({decision}). "
            f"Baseline CTR: {b['ctr']:.1%}, Challenger CTR: {c['ctr']:.1%} "
            f"(p={p_final:.4f})"
        )

    # Clear experiment for next round
    clear_active_experiment()
    _reset_variant_config()

    return summary


def _promote_challenger(experiment: dict):
    """Promote challenger copy to become the new baseline."""
    challenger_copy = experiment.get("challenger_copy", {})
    if not challenger_copy:
        log.warning("No challenger copy found in experiment. Cannot promote.")
        return

    baseline = BASELINE_FILE.read_text()

    for key, value in challenger_copy.items():
        # Find and replace the value in baseline.md
        # Format: key: "value"
        import re
        pattern = rf'^({re.escape(key)}:\s*)".*?"'
        replacement = rf'\1"{value}"'
        baseline_new = re.sub(pattern, replacement, baseline, flags=re.MULTILINE)
        if baseline_new != baseline:
            baseline = baseline_new
        else:
            # Try without quotes (some values span lines)
            pattern = rf'^({re.escape(key)}:\s*).*$'
            replacement = rf'\1"{value}"'
            baseline = re.sub(pattern, replacement, baseline, flags=re.MULTILINE)

    # Update last updated date
    baseline = re.sub(
        r'^# Last updated:.*$',
        f'# Last updated: {date.today().isoformat()}',
        baseline,
        flags=re.MULTILINE,
    )

    BASELINE_FILE.write_text(baseline)
    log.info("Promoted challenger to baseline. Updated baseline.md.")


def _reset_variant_config():
    """Reset variant-config.json to baseline-only (no challenger)."""
    config = json.loads(VARIANT_CONFIG_FILE.read_text())
    config["experiment_id"] = None
    config["started_at"] = None
    config["hypothesis"] = None
    config["challenger"] = None
    VARIANT_CONFIG_FILE.write_text(json.dumps(config, indent=2))
    log.info("Reset variant-config.json (no active challenger).")


# ─────────────────────────────────────────────
# PHASE 2: GENERATE
# ─────────────────────────────────────────────

def phase_generate(last_summary: str) -> dict:
    """Call Claude to generate a challenger config.

    Returns dict with:
      - experiment_id: str
      - hypothesis: str
      - challenger_copy: dict of {element_key: new_text}
      - elements_changed: str (human-readable summary)
    """
    baseline_config = BASELINE_FILE.read_text()
    resource_context = RESOURCE_FILE.read_text()
    recent_history = get_recent_experiments(20)
    has_history = bool(recent_history)

    learnings_context = ""
    if LEARNINGS_FILE.exists():
        learnings_context = LEARNINGS_FILE.read_text()

    if has_history:
        experimentation_guidance = """You have experiment history. SHIFT TO EXPLOITATION:
- Study the history carefully. What patterns emerge? What's working?
- Make targeted improvements based on data, not guesses.
- If you see a clear winning direction, double down with refinements.
- You CAN still make bold changes if data suggests a fundamentally different approach,
  but ground your decisions in results."""
    else:
        experimentation_guidance = """No history yet — this is the first experiment. MAXIMIZE EXPLORATION:
- Go bold: test a radically different value proposition frame.
- Make BIG swings. Failed experiments cost nothing. Playing it safe wastes the first test.
- Pick the highest-impact elements first: hero headline, subheadline, and CTA button text.
- Reference the CRO-informed mutation strategy in resource.md for framework ideas."""

    experiment_id = f"exp-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    prompt = f"""You are an autonomous landing page optimization agent in an autoresearch loop.

## HOW THIS SYSTEM WORKS

This system is inspired by Karpathy's autoresearch pattern. An AI agent runs experiments
autonomously in a tight loop, using an objective metric as the sole feedback signal.

Architecture:
- baseline.md = current best landing page copy (the file being mutated)
- resource.md = product context, ICP, constraints, CRO strategy
- variant-config.json = deployed config that ab-test.js reads to swap copy
- results.log = append-only experiment history

The loop runs daily:
1. HARVEST: read CTR from GA4 (CTA clicks / page views, segmented by variant)
2. GENERATE: you (this prompt) produce challenger copy
3. DEPLOY: variant-config.json updated, ab-test.js swaps text for 50% of visitors
4. MEASURE: click-through rate on CTA buttons is the objective metric
5. PROMOTE OR REVERT: if challenger wins (p<0.05), it becomes new baseline

The page gets ~34 visitors/day (~17 per variant). Experiments run 7-21 days.
Because traffic is low, BOLD mutations with large effect sizes are critical —
subtle wording changes won't reach significance. Test fundamentally different
psychological frames, not minor rewrites.

Your role: you are the mutation engine. Output challenger copy that tests a specific
hypothesis. You have full freedom to change any mutable text element.

Key principles:
- ONE OBJECTIVE METRIC: CTA click-through rate. Not "sounds better." Clicks are the
  only thing that matters.
- REFRAME, DON'T REPHRASE: every challenger must test a fundamentally different angle
  or psychological frame, not just different words for the same message.
- ONE BIG HYPOTHESIS: state clearly what you're testing and why.
- MOBILE-FIRST COPY: headlines under 8 words, subheadlines under 20 words. Most vendors
  read on phones.
- BOLD EXPERIMENTATION: with ~17 visitors/variant/day, only large effect sizes will
  reach significance. Subtle changes are wasted experiments.

## EXPLORATION vs EXPLOITATION

{experimentation_guidance}

## CURRENT BASELINE (the copy being mutated)

{baseline_config}

## PRODUCT & BUSINESS CONTEXT + CRO STRATEGY

{resource_context}

## EXPERIMENT HISTORY

{recent_history if recent_history else "(No history yet — first experiment)"}

## LAST HARVEST RESULTS

{last_summary}

## ACCUMULATED LEARNINGS

{learnings_context if learnings_context else "(No learnings yet)"}

## WHAT YOU CAN CHANGE

Any text element listed in baseline.md. You do NOT need to change all elements —
focus on the ones that matter most for your hypothesis. Typical high-impact targets:
- hero_headline, hero_subheadline (first thing visitors see)
- mid_page_hook (second hook below the fold)
- cta_button_text (the action trigger — appears on both CTA buttons)
- feature_card titles and descriptions
- section headings

## WHAT YOU CANNOT CHANGE

- Images, layout, colors, CSS, page structure
- CTA link destinations (always go to /signup/basic-annual-2026)
- Pricing: "$10/mo" must remain accurate wherever it appears
- Vendor count: "700+" must remain accurate
- comparison_homegrown_1 must stay "$10/mo with everything included"
- No false urgency, no income claims, no dishonest content

## OUTPUT FORMAT (critical — malformed output will crash the system)

Output a valid JSON object with this exact structure. No markdown fences, no commentary,
no explanation before or after the JSON. ONLY the JSON object.

{{{{
  "experiment_id": "{experiment_id}",
  "hypothesis": "This experiment tests whether [FRAME/ANGLE] converts better than [CURRENT FRAME] because [REASONING]",
  "elements_changed": "hero_headline, hero_subheadline, cta_button_text",
  "challenger_copy": {{{{
    "hero_headline": "New headline text here",
    "hero_subheadline": "New subheadline text here",
    "cta_button_text": "New CTA text"
  }}}}
}}}}

Rules for the JSON:
- "experiment_id" must be exactly "{experiment_id}"
- "hypothesis" must clearly state what psychological frame is being tested
- "elements_changed" is a comma-separated list of which keys you changed
- "challenger_copy" contains ONLY the elements you want to change (not all elements)
- Keys in challenger_copy must exactly match the keys in baseline.md
- For CTA button text, use key "cta_button_text" — it will be applied to both buttons
- Values must be plain text (no HTML tags except <br> for line breaks in headings)
- Headings that have line breaks use <br> tag: "Line One<br>Line Two"
"""

    client = anthropic.Anthropic()

    log.info("Calling Claude to generate challenger...")
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract text from response
    text_blocks = [block.text.strip() for block in response.content if block.type == "text"]
    if not text_blocks:
        raise RuntimeError("Claude returned no text content")

    raw_output = text_blocks[-1]

    # Parse JSON — strip any markdown fences if present
    clean = raw_output.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        clean = clean.strip()

    try:
        challenger = json.loads(clean)
    except json.JSONDecodeError as e:
        log.error("Failed to parse Claude output as JSON: %s", e)
        log.error("Raw output:\n%s", raw_output[:2000])
        raise RuntimeError(f"Claude output is not valid JSON: {e}")

    # Validate structure
    required_keys = ["experiment_id", "hypothesis", "elements_changed", "challenger_copy"]
    for key in required_keys:
        if key not in challenger:
            raise RuntimeError(f"Missing required key in challenger: {key}")

    if not isinstance(challenger["challenger_copy"], dict):
        raise RuntimeError("challenger_copy must be a dict")

    if not challenger["challenger_copy"]:
        raise RuntimeError("challenger_copy is empty — no elements to change")

    # Validate content constraints
    _validate_challenger(challenger["challenger_copy"])

    log.info(
        "Challenger generated: %s — %d elements changed",
        challenger["hypothesis"][:80],
        len(challenger["challenger_copy"]),
    )

    return challenger


def _validate_challenger(challenger_copy: dict):
    """Validate challenger copy doesn't violate content constraints."""
    import re

    # Check prohibited exact values
    for key, required_value in PROHIBITED_CHANGES.items():
        if key in challenger_copy and challenger_copy[key] != required_value:
            raise RuntimeError(
                f"Prohibited change: {key} must be '{required_value}', "
                f"got '{challenger_copy[key]}'"
            )

    # Check all values for prohibited patterns
    for key, value in challenger_copy.items():
        # Character length limits (mobile-first)
        if "headline" in key and len(value.replace("<br>", "")) > 60:
            log.warning("Headline '%s' is %d chars (recommend <60)", key, len(value))

        if "desc" in key and len(value) > 200:
            log.warning("Description '%s' is %d chars (recommend <200)", key, len(value))


# ─────────────────────────────────────────────
# PHASE 3: DEPLOY
# ─────────────────────────────────────────────

def phase_deploy(challenger: dict, dry_run: bool = False):
    """Deploy the challenger by updating variant-config.json.

    The ab-test.js script on /signup fetches this file on each page load.
    """
    # Load current variant config (has selectors)
    config = json.loads(VARIANT_CONFIG_FILE.read_text())

    # Map challenger_copy keys to the config
    challenger_copy = challenger["challenger_copy"]

    # Handle cta_button_text → apply to both CTA buttons
    if "cta_button_text" in challenger_copy:
        cta_text = challenger_copy.pop("cta_button_text")
        challenger_copy["cta_button_1"] = cta_text
        challenger_copy["cta_button_2"] = cta_text

    # Verify all challenger keys have corresponding selectors
    for key in challenger_copy:
        if key not in config["selectors"]:
            log.warning(
                "Challenger key '%s' has no CSS selector — will be ignored by ab-test.js",
                key,
            )

    config["experiment_id"] = challenger["experiment_id"]
    config["started_at"] = datetime.now(timezone.utc).isoformat()
    config["hypothesis"] = challenger["hypothesis"]
    config["challenger"] = challenger_copy

    if dry_run:
        log.info("DRY RUN — would deploy variant-config.json:")
        log.info(json.dumps(config, indent=2))
        return

    # Write variant config
    VARIANT_CONFIG_FILE.write_text(json.dumps(config, indent=2))
    log.info("Updated variant-config.json with challenger.")

    # Save active experiment
    experiment = {
        "experiment_id": challenger["experiment_id"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": challenger["hypothesis"],
        "elements_changed": challenger["elements_changed"],
        "challenger_copy": challenger_copy,
    }
    save_active_experiment(experiment)
    log.info("Saved active experiment: %s", challenger["experiment_id"])


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Landing Page A/B Optimizer")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't deploy")
    parser.add_argument("--harvest-only", action="store_true", help="Only harvest results")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Landing Page Optimizer — %s", datetime.now(timezone.utc).isoformat())
    log.info("=" * 60)

    # Phase 1: Harvest
    log.info("─── PHASE 1: HARVEST ───")
    harvest_summary = phase_harvest()
    log.info("Harvest: %s", harvest_summary)

    if args.harvest_only:
        log.info("Harvest-only mode. Done.")
        return

    # Check if experiment is still running
    experiment = load_active_experiment()
    if experiment and experiment.get("experiment_id"):
        log.info("Experiment %s still running. Skipping generate/deploy.", experiment["experiment_id"])
        return

    # Phase 2: Generate
    log.info("─── PHASE 2: GENERATE ───")
    challenger = phase_generate(harvest_summary)

    # Phase 3: Deploy
    log.info("─── PHASE 3: DEPLOY ───")
    phase_deploy(challenger, dry_run=args.dry_run)

    if args.dry_run:
        log.info("Dry run complete. No changes deployed.")
    else:
        log.info("Experiment %s deployed. ab-test.js will pick up changes on next page load.",
                 challenger["experiment_id"])

    log.info("=" * 60)
    log.info("Done.")


if __name__ == "__main__":
    main()
