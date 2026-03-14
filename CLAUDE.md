# Landing Page Optimizer — Autonomous A/B Testing for /signup

An autonomous landing page copy optimization system inspired by Karpathy's autoresearch pattern. Runs daily on GitHub Actions cron — no human input needed after setup.

**How it works:** Daily at 6am UTC: harvest CTR from GA4 → statistical significance test → promote winner → Claude generates challenger copy → update variant-config.json → ab-test.js on /signup reads config and swaps copy for 50% of visitors → repeat.

**Optimization metric:** Click-through rate (CTA clicks / page views), segmented by `hg_variant` GA4 user property.

## Architecture

```
orchestrator.py          — Main 3-phase loop (harvest → generate → deploy)
ga4_client.py            — GA4 Data API wrapper (read CTR by variant)

config/baseline.md       — Current best copy (all mutable text elements)
config/page-elements.md  — CSS selector → node ID mapping (immutable reference)

data/resource.md         — Product context, ICP, constraints
data/active_experiment.json — Currently running experiment (1 at a time)
data/variant-config.json — Served to ab-test.js (live A/B config)

results/results.log      — Append-only JSONL experiment history
results/experiments/     — Full experiment records
results/learnings.md     — Auto-generated insights

scripts/ab-test.js       — Client-side variant switcher (~50 lines)
```

## Key Numbers

| Parameter | Value |
|-----------|-------|
| Traffic | ~34 visitors/day (~17 per variant) |
| Minimum experiment duration | 7 days |
| Maximum experiment duration | 21 days |
| Min visitors per arm for significance | 100 |
| Early kill threshold | CTR < 50% of baseline after 50+ visitors |
| Statistical test | Two-proportion z-test (p<0.05) |
| Cron schedule | Daily at 6am UTC |
| GA4 Property | 427786646 |

## What Can Be Mutated

- Hero headline, subheadline
- Mid-page hook text
- CTA button text (x2)
- Feature card titles and descriptions (3 cards)
- Section headings and descriptions
- 6 feature detail card titles and descriptions
- Comparison section heading and items

## What CANNOT Be Changed

- Images, layout, colors, CSS, page structure
- CTA link destinations
- Pricing ($10/mo) — factual, must remain accurate
- Vendor count (700+) — factual, must remain accurate
- Any statistics or data claims

## Safety Rules

- **ab-test.js fails silently** — if config fetch fails, page shows baseline unchanged
- **Schema validation** before committing variant-config.json
- **Early kill** — auto-revert if challenger CTR < 50% of baseline after 50+ visitors
- **Factual validation** — orchestrator checks for prohibited content changes
- **Emergency kill** — delete variant-config.json or remove script from Webflow to disable
- **NEVER overwrite** results/results.log or results/learnings.md — append-only
- **NEVER change** CTA link destinations, pricing, or statistics

## Setup

- `.env` has ANTHROPIC_API_KEY and GA4_SERVICE_ACCOUNT_JSON (path to service account key file)
- `config/baseline.md` has current live copy
- `data/resource.md` has product context
- `scripts/ab-test.js` is installed on /signup via Webflow Scripts API
- Run `python orchestrator.py --dry-run` to test challenger generation
- Push to GitHub, add secrets, enable Actions for autonomous operation
