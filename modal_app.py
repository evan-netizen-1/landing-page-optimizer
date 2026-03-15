"""
modal_app.py — Modal scheduled function for the landing-page-optimizer.

Replaces GitHub Actions cron with a reliable Modal cron.
Runs daily at 6am UTC (same schedule as before, just reliable).

IMPORTANT: This optimizer must push variant-config.json to GitHub because
the live ab-test.js on the Webflow page fetches it from:
https://raw.githubusercontent.com/evan-netizen-1/landing-page-optimizer/main/data/variant-config.json

Deploy: modal deploy modal_app.py
"""

import os
import json
import subprocess
import modal

app = modal.App("landing-page-optimizer")

repo_dir = os.path.dirname(os.path.abspath(__file__))

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install(
        "anthropic>=0.42.0",
        "google-analytics-data>=0.18.0",
        "google-auth>=2.0.0",
        "python-dotenv>=1.0.0",
        "fastapi",
    )
    .add_local_dir(repo_dir, remote_path="/app")
)

# Secrets: ANTHROPIC_API_KEY, GA4_SERVICE_ACCOUNT_JSON, GA4_PROPERTY_ID, GITHUB_TOKEN
secrets = modal.Secret.from_name("landing-page-optimizer-secrets")

# Persistent volume for mutable state
volume = modal.Volume.from_name("landing-page-optimizer-data", create_if_missing=True)
VOL = "/vol"


def _sync_state_to_volume():
    """Copy mutable state files from /app to /vol if they don't exist yet."""
    import shutil
    os.makedirs(f"{VOL}/data", exist_ok=True)
    os.makedirs(f"{VOL}/results", exist_ok=True)
    os.makedirs(f"{VOL}/results/experiments", exist_ok=True)
    os.makedirs(f"{VOL}/config", exist_ok=True)

    state_files = [
        ("data/active_experiment.json", f"{VOL}/data/active_experiment.json"),
        ("data/variant-config.json", f"{VOL}/data/variant-config.json"),
        ("config/baseline.md", f"{VOL}/config/baseline.md"),
        ("results/results.log", f"{VOL}/results/results.log"),
        ("results/learnings.md", f"{VOL}/results/learnings.md"),
    ]

    for src_rel, dst in state_files:
        src = f"/app/{src_rel}"
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copy2(src, dst)


def _patch_paths():
    """Override orchestrator path constants to point at the Modal volume."""
    import sys
    sys.path.insert(0, "/app")
    import orchestrator

    from pathlib import Path
    vol = Path(VOL)

    orchestrator.ACTIVE_EXPERIMENT_FILE = vol / "data" / "active_experiment.json"
    orchestrator.BASELINE_FILE = vol / "config" / "baseline.md"
    orchestrator.VARIANT_CONFIG_FILE = vol / "data" / "variant-config.json"
    orchestrator.RESULTS_LOG = vol / "results" / "results.log"
    orchestrator.LEARNINGS_FILE = vol / "results" / "learnings.md"

    # ROOT stays at /app for reading resource.md and page-elements.md
    orchestrator.ROOT = Path("/app")

    return orchestrator


def _push_to_github():
    """Push updated variant-config.json and state files to GitHub.

    The live ab-test.js fetches variant-config.json from GitHub raw,
    so we MUST push for changes to go live on the Webflow page.
    """
    import logging
    log = logging.getLogger("modal-lp-optimizer")

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        log.warning("No GITHUB_TOKEN — skipping git push (variant changes won't go live!)")
        return False

    repo = "evan-netizen-1/landing-page-optimizer"
    repo_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    work_dir = "/tmp/lp-repo"

    try:
        # Clone, copy state files, commit, push
        subprocess.run(["rm", "-rf", work_dir], check=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, work_dir],
            check=True, capture_output=True, timeout=60,
        )

        import shutil
        # Copy mutable files from volume to repo
        files_to_push = [
            (f"{VOL}/data/variant-config.json", f"{work_dir}/data/variant-config.json"),
            (f"{VOL}/data/active_experiment.json", f"{work_dir}/data/active_experiment.json"),
            (f"{VOL}/config/baseline.md", f"{work_dir}/config/baseline.md"),
            (f"{VOL}/results/results.log", f"{work_dir}/results/results.log"),
            (f"{VOL}/results/learnings.md", f"{work_dir}/results/learnings.md"),
        ]
        for src, dst in files_to_push:
            if os.path.exists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        # Git commit and push
        subprocess.run(
            ["git", "config", "user.name", "lp-optimizer[bot]"],
            cwd=work_dir, check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "bot@users.noreply.github.com"],
            cwd=work_dir, check=True,
        )
        subprocess.run(
            ["git", "add", "-A"],
            cwd=work_dir, check=True,
        )

        # Check if there are changes
        diff = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=work_dir, capture_output=True,
        )
        if diff.returncode == 0:
            log.info("No changes to push to GitHub")
            return True

        from datetime import datetime
        msg = f"exp {datetime.utcnow().strftime('%Y-%m-%d')}: auto-optimize (Modal)"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=work_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=work_dir, check=True, capture_output=True, timeout=60,
        )
        log.info("Pushed results to GitHub — variant-config.json is live")
        return True

    except Exception as e:
        log.error("Git push failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Scheduled: Daily at 6am UTC
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=[secrets],
    volumes={VOL: volume},
    timeout=1800,
    schedule=modal.Cron("0 6 * * *"),
)
def run_optimizer():
    """Run the full harvest → generate → deploy loop, then push to GitHub."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("modal-lp-optimizer")

    volume.reload()
    _sync_state_to_volume()
    orchestrator = _patch_paths()

    try:
        log.info("Starting landing-page-optimizer run")
        orchestrator.main()
        log.info("Landing-page-optimizer run complete")
    except Exception as e:
        log.error("Landing-page-optimizer run failed: %s", e, exc_info=True)
        raise
    finally:
        volume.commit()

    # Push results to GitHub so variant-config.json goes live
    _push_to_github()


# ---------------------------------------------------------------------------
# Manual trigger endpoint
# ---------------------------------------------------------------------------

@app.function(
    image=image,
    secrets=[secrets],
    volumes={VOL: volume},
    timeout=1800,
)
@modal.fastapi_endpoint(method="POST", docs=True)
def trigger(data: dict = {}):
    """Manual trigger. POST {} to run, or {"dry_run": true} / {"harvest_only": true}."""
    import sys
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    dry_run = data.get("dry_run", False)
    harvest_only = data.get("harvest_only", False)

    volume.reload()
    _sync_state_to_volume()
    orchestrator = _patch_paths()

    try:
        sys.argv = ["orchestrator.py"]
        if dry_run:
            sys.argv.append("--dry-run")
        if harvest_only:
            sys.argv.append("--harvest-only")

        orchestrator.main()
        volume.commit()

        if not dry_run:
            _push_to_github()

        return {"status": "success"}
    except Exception as e:
        volume.commit()
        return {"status": "error", "reason": str(e)}
