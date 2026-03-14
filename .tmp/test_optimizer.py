"""
Comprehensive tests for the landing page optimizer system.

Covers:
  - two_proportion_z_test: statistical correctness
  - is_significant: wrapper logic
  - variant-config.json: valid JSON, all selectors present, selector string format
  - CSS selector consistency: variant-config selectors match page-elements.md node IDs
  - Safety constraints in orchestrator (_validate_challenger, PROHIBITED_CHANGES)
  - Dry-run flag wiring in phase_deploy
  - JSON parsing / markdown-fence stripping in phase_generate output handling
  - Edge cases: zero visitors, identical rates, all clicks, no clicks
"""

import json
import math
import os
import sys
import re
import copy
import tempfile
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# PATH SETUP — import orchestrator without executing main()
# ---------------------------------------------------------------------------
ROOT = Path("/Users/evanknox/Desktop/Claude/landing-page-optimizer")
sys.path.insert(0, str(ROOT))

# Patch out heavy imports that require credentials before importing orchestrator
import unittest.mock as mock

# We stub the external packages so the module-level import doesn't fail
# when google-analytics-data or anthropic are not installed.
sys.modules.setdefault("anthropic", mock.MagicMock())
sys.modules.setdefault("dotenv", mock.MagicMock())
# dotenv.load_dotenv must be callable at module level
dotenv_mock = sys.modules["dotenv"]
dotenv_mock.load_dotenv = mock.MagicMock()

# google hierarchy
for mod in [
    "google",
    "google.analytics",
    "google.analytics.data_v1beta",
    "google.analytics.data_v1beta.types",
    "google.oauth2",
    "google.oauth2.service_account",
]:
    sys.modules.setdefault(mod, mock.MagicMock())

import orchestrator  # noqa: E402  (imported after mocks)

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

VARIANT_CONFIG_PATH = ROOT / "data" / "variant-config.json"
PAGE_ELEMENTS_PATH = ROOT / "config" / "page-elements.md"


def _load_variant_config():
    return json.loads(VARIANT_CONFIG_PATH.read_text())


def _extract_node_ids_from_page_elements() -> set:
    """Parse page-elements.md and return all node IDs listed in the table."""
    text = PAGE_ELEMENTS_PATH.read_text()
    # Rows look like: | hero_headline | 87a34d83-... | [data-w-id="..."], ...
    node_ids = set()
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            node_id = parts[2].strip()
            # Node IDs are UUID-like hex strings
            if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', node_id):
                node_ids.add(node_id)
    return node_ids


def _extract_node_ids_from_selectors(selectors: dict) -> set:
    """Extract bare node IDs from CSS selectors like [data-w-id="<uuid>"]."""
    ids = set()
    for selector in selectors.values():
        m = re.search(r'data-w-id="([^"]+)"', selector)
        if m:
            ids.add(m.group(1))
    return ids


# ===========================================================================
# 1. two_proportion_z_test
# ===========================================================================

class TestTwoProportionZTest:

    def test_zero_n1_returns_neutral(self):
        z, p = orchestrator.two_proportion_z_test(0.1, 0, 0.2, 100)
        assert z == 0.0
        assert p == 1.0, f"Expected p=1.0 for n1=0, got {p}"

    def test_zero_n2_returns_neutral(self):
        z, p = orchestrator.two_proportion_z_test(0.1, 100, 0.2, 0)
        assert z == 0.0
        assert p == 1.0

    def test_pooled_rate_zero_returns_neutral(self):
        # Both rates = 0, pooled = 0
        z, p = orchestrator.two_proportion_z_test(0.0, 100, 0.0, 100)
        assert z == 0.0
        assert p == 1.0

    def test_pooled_rate_one_returns_neutral(self):
        # Both rates = 1
        z, p = orchestrator.two_proportion_z_test(1.0, 100, 1.0, 100)
        assert z == 0.0
        assert p == 1.0

    def test_identical_rates_gives_z_zero(self):
        z, p = orchestrator.two_proportion_z_test(0.2, 200, 0.2, 200)
        assert abs(z) < 1e-9, f"Expected z≈0 for identical rates, got {z}"
        # p should be 0.5 for a one-tailed test with z=0
        assert abs(p - 0.5) < 0.01, f"Expected p≈0.5, got {p}"

    def test_clearly_significant_result(self):
        # 20% vs 40% with large N — should be highly significant
        z, p = orchestrator.two_proportion_z_test(0.20, 500, 0.40, 500)
        assert z > 6, f"Expected z>6 for large effect, got {z}"
        assert p < 0.0001, f"Expected p<0.0001, got {p}"

    def test_standard_significance_threshold(self):
        # z ≈ 1.96 should give p ≈ 0.025 (one-tailed) — just above significance
        # p = 0.5 * erfc(1.96 / sqrt(2)) ≈ 0.025
        z_manual = 1.96
        p_expected = 0.5 * math.erfc(z_manual / math.sqrt(2))
        # Use rates that produce z close to 1.96 (approximate)
        # 10% vs 14% with n=2000 each should be well into significance territory
        z, p = orchestrator.two_proportion_z_test(0.10, 2000, 0.14, 2000)
        assert z > 1.96, f"Expected z>1.96, got {z}"
        assert p < 0.05, f"Expected p<0.05, got {p}"

    def test_challenger_worse_gives_negative_z(self):
        # p2 < p1 → z should be negative, p > 0.5
        z, p = orchestrator.two_proportion_z_test(0.30, 200, 0.10, 200)
        assert z < 0, f"Expected negative z for worse challenger, got {z}"
        assert p > 0.5, f"Expected p>0.5 for negative z, got {p}"

    def test_p_value_in_valid_range(self):
        z, p = orchestrator.two_proportion_z_test(0.15, 150, 0.22, 150)
        assert 0.0 <= p <= 1.0, f"p-value out of range: {p}"

    def test_asymmetric_sample_sizes(self):
        # Should not crash with very different n values
        z, p = orchestrator.two_proportion_z_test(0.10, 1000, 0.15, 50)
        assert isinstance(z, float)
        assert isinstance(p, float)
        assert 0.0 <= p <= 1.0

    def test_formula_correctness_manual(self):
        """Verify against hand-computed values."""
        p1, n1, p2, n2 = 0.10, 200, 0.20, 200
        p_pool = (0.10 * 200 + 0.20 * 200) / 400  # = 0.15
        se = math.sqrt(0.15 * 0.85 * (1/200 + 1/200))
        z_expected = (0.20 - 0.10) / se
        p_expected = 0.5 * math.erfc(z_expected / math.sqrt(2))

        z, p = orchestrator.two_proportion_z_test(p1, n1, p2, n2)
        assert abs(z - z_expected) < 1e-9, f"z mismatch: {z} vs {z_expected}"
        assert abs(p - p_expected) < 1e-9, f"p mismatch: {p} vs {p_expected}"


# ===========================================================================
# 2. is_significant
# ===========================================================================

class TestIsSignificant:

    def test_zero_baseline_views_returns_false(self):
        sig, z, p = orchestrator.is_significant(0, 0, 10, 100)
        assert sig is False
        assert z == 0.0
        assert p == 1.0

    def test_zero_challenger_views_returns_false(self):
        sig, z, p = orchestrator.is_significant(10, 100, 0, 0)
        assert sig is False
        assert z == 0.0
        assert p == 1.0

    def test_clearly_significant_promotes(self):
        # 10% baseline, 30% challenger, 500 each — obviously significant
        sig, z, p = orchestrator.is_significant(50, 500, 150, 500)
        assert sig is True, f"Expected significant, p={p}"
        assert z > 0
        assert p < 0.05

    def test_not_significant_with_small_effect_and_small_n(self):
        # 10% vs 12%, only 50 visitors each — not significant
        sig, z, p = orchestrator.is_significant(5, 50, 6, 50)
        assert sig is False, f"Expected not significant, p={p}"
        assert p >= 0.05

    def test_custom_alpha_strict(self):
        # Use alpha=0.01 — a result significant at 0.05 may not be at 0.01
        # 10% vs 15%, n=300: likely not significant at 0.01
        sig_05, _, p = orchestrator.is_significant(30, 300, 45, 300, alpha=0.05)
        sig_01, _, _ = orchestrator.is_significant(30, 300, 45, 300, alpha=0.01)
        if sig_05:
            # If it's significant at 0.05, test that 0.01 is more restrictive or equal
            assert not sig_01 or p < 0.01

    def test_custom_alpha_relaxed(self):
        # alpha=0.10 — border-line cases become significant
        # p≈0.07 would not be sig at 0.05 but would be at 0.10
        sig_05, _, p = orchestrator.is_significant(15, 200, 25, 200, alpha=0.05)
        sig_10, _, _ = orchestrator.is_significant(15, 200, 25, 200, alpha=0.10)
        # At relaxed alpha, significance can only be equal or more permissive
        assert (sig_10 >= sig_05), "alpha=0.10 should be at least as permissive as alpha=0.05"

    def test_returns_tuple_of_three(self):
        result = orchestrator.is_significant(10, 100, 20, 100)
        assert len(result) == 3
        sig, z, p = result
        assert isinstance(sig, bool)
        assert isinstance(z, float)
        assert isinstance(p, float)

    def test_challenger_worse_not_significant(self):
        # Challenger worse than baseline → one-tailed test should NOT be significant
        sig, z, p = orchestrator.is_significant(100, 200, 10, 200)
        assert sig is False, "Worse challenger should not be deemed significant"
        assert z < 0

    def test_identical_rates_not_significant(self):
        sig, z, p = orchestrator.is_significant(20, 100, 20, 100)
        assert sig is False
        assert abs(z) < 1e-9

    def test_rates_derived_correctly(self):
        """is_significant should compute b_rate=b_clicks/b_views."""
        # 50 clicks / 200 views = 25%; 80 clicks / 200 views = 40%
        sig, z, p = orchestrator.is_significant(50, 200, 80, 200)
        z2, p2 = orchestrator.two_proportion_z_test(0.25, 200, 0.40, 200)
        assert abs(z - z2) < 1e-9
        assert abs(p - p2) < 1e-9


# ===========================================================================
# 3. variant-config.json — structure and validity
# ===========================================================================

class TestVariantConfigJson:

    def setup_method(self):
        self.config = _load_variant_config()

    def test_valid_json_loads(self):
        assert isinstance(self.config, dict)

    def test_top_level_keys_present(self):
        for key in ("experiment_id", "started_at", "hypothesis", "selectors", "baseline", "challenger"):
            assert key in self.config, f"Missing top-level key: {key}"

    def test_selectors_is_dict(self):
        assert isinstance(self.config["selectors"], dict)

    def test_selectors_not_empty(self):
        assert len(self.config["selectors"]) > 0

    def test_all_selector_values_are_strings(self):
        for key, val in self.config["selectors"].items():
            assert isinstance(val, str), f"Selector '{key}' value is not a string: {val!r}"

    def test_all_selectors_contain_data_w_id(self):
        for key, val in self.config["selectors"].items():
            assert "data-w-id=" in val, (
                f"Selector '{key}' does not use data-w-id attribute: {val!r}"
            )

    def test_cta_buttons_present(self):
        selectors = self.config["selectors"]
        assert "cta_button_1" in selectors, "Missing cta_button_1 selector"
        assert "cta_button_2" in selectors, "Missing cta_button_2 selector"

    def test_hero_elements_present(self):
        selectors = self.config["selectors"]
        assert "hero_headline" in selectors
        assert "hero_subheadline" in selectors

    def test_feature_cards_present(self):
        selectors = self.config["selectors"]
        for i in range(1, 4):
            assert f"feature_card_{i}_title" in selectors
            assert f"feature_card_{i}_desc" in selectors

    def test_detail_cards_present(self):
        selectors = self.config["selectors"]
        for i in range(1, 7):
            assert f"detail_card_{i}_title" in selectors
            assert f"detail_card_{i}_desc" in selectors

    def test_section_headings_present(self):
        selectors = self.config["selectors"]
        for key in ("section_everything_heading", "section_setup_heading",
                    "section_payments_heading", "section_tools_heading"):
            assert key in selectors, f"Missing section heading: {key}"

    def test_comparison_heading_present(self):
        assert "comparison_heading" in self.config["selectors"]

    def test_initial_state_no_active_experiment(self):
        # In the repo's initial/reset state, experiment_id and challenger should be null
        # (They may be set during a live run, so we just check the types are correct when null)
        exp_id = self.config["experiment_id"]
        challenger = self.config["challenger"]
        assert exp_id is None or isinstance(exp_id, str)
        assert challenger is None or isinstance(challenger, dict)


# ===========================================================================
# 4. CSS Selector consistency — variant-config.json vs page-elements.md
# ===========================================================================

class TestSelectorConsistency:

    def setup_method(self):
        self.config = _load_variant_config()
        self.config_selectors = self.config["selectors"]
        self.page_element_node_ids = _extract_node_ids_from_page_elements()
        self.config_node_ids = _extract_node_ids_from_selectors(self.config_selectors)

    def test_page_elements_parsed_nonempty(self):
        assert len(self.page_element_node_ids) > 0, \
            "No node IDs extracted from page-elements.md — check parsing"

    def test_every_config_selector_node_id_exists_in_page_elements(self):
        """Every node ID referenced in variant-config selectors must appear in page-elements.md."""
        missing = self.config_node_ids - self.page_element_node_ids
        assert not missing, (
            f"Node IDs in variant-config.json not found in page-elements.md: {missing}"
        )

    def test_all_config_keys_have_matching_node_id(self):
        """Each selector in variant-config.json must contain a recognisable UUID."""
        uuid_pattern = re.compile(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        )
        for key, selector in self.config_selectors.items():
            assert uuid_pattern.search(selector), (
                f"Selector for '{key}' contains no UUID-format node ID: {selector!r}"
            )

    def test_hero_headline_node_id_matches(self):
        selector = self.config_selectors.get("hero_headline", "")
        assert "87a34d83-50aa-82af-649c-d1db1ce92307" in selector

    def test_hero_subheadline_node_id_matches(self):
        selector = self.config_selectors.get("hero_subheadline", "")
        assert "dc19941b-af81-bfbb-9820-705ef670de8e" in selector

    def test_cta_button_1_node_id_matches(self):
        selector = self.config_selectors.get("cta_button_1", "")
        assert "7341f29e-8b06-6659-f639-a254ad431094" in selector

    def test_cta_button_2_node_id_matches(self):
        selector = self.config_selectors.get("cta_button_2", "")
        assert "7341f29e-8b06-6659-f639-a254ad431096" in selector

    def test_mid_page_hook_node_id_matches(self):
        selector = self.config_selectors.get("mid_page_hook", "")
        assert "c6096f36-f380-f68c-8f44-f6001938009c" in selector


# ===========================================================================
# 5. Safety constraints — _validate_challenger
# ===========================================================================

class TestValidateChallenger:

    def test_valid_challenger_passes(self):
        """A normal challenger with no prohibited content should pass without error."""
        challenger_copy = {
            "hero_headline": "Stop Losing Sales Between Market Days",
            "hero_subheadline": "New subheadline text here",
            "cta_button_text": "Get Your Free Storefront",
        }
        try:
            orchestrator._validate_challenger(challenger_copy)
        except RuntimeError as e:
            raise AssertionError(f"Valid challenger raised RuntimeError: {e}")

    def test_prohibited_key_wrong_value_raises(self):
        """Changing comparison_homegrown_1 from its required value must raise."""
        challenger_copy = {
            "comparison_homegrown_1": "$5/mo with everything included",  # wrong price
        }
        try:
            orchestrator._validate_challenger(challenger_copy)
            raise AssertionError("Expected RuntimeError for prohibited change, got none")
        except RuntimeError as e:
            assert "comparison_homegrown_1" in str(e) or "Prohibited" in str(e)

    def test_prohibited_key_correct_value_passes(self):
        """comparison_homegrown_1 with the correct value must not raise."""
        challenger_copy = {
            "comparison_homegrown_1": "$10/mo with everything included",
        }
        try:
            orchestrator._validate_challenger(challenger_copy)
        except RuntimeError as e:
            raise AssertionError(f"Correct prohibited value raised RuntimeError: {e}")

    def test_long_headline_emits_warning_not_error(self):
        """Overly long headline should warn but NOT raise."""
        long_headline = "A" * 100  # 100 chars, well over the 60-char soft limit
        challenger_copy = {"hero_headline": long_headline}
        # Should not raise
        try:
            orchestrator._validate_challenger(challenger_copy)
        except RuntimeError as e:
            raise AssertionError(f"Long headline raised error instead of warning: {e}")

    def test_empty_challenger_copy_is_valid_for_validator(self):
        """_validate_challenger itself doesn't enforce non-empty (that's done upstream)."""
        try:
            orchestrator._validate_challenger({})
        except RuntimeError:
            raise AssertionError("Empty dict should not raise in _validate_challenger")


# ===========================================================================
# 6. phase_deploy — dry-run mode
# ===========================================================================

class TestPhaseDeploy:

    def setup_method(self):
        """Use a temp directory to avoid touching real files."""
        self.tmpdir = Path(tempfile.mkdtemp())
        # Copy variant-config.json to tmp
        self.fake_config = self.tmpdir / "variant-config.json"
        self.fake_config.write_text(VARIANT_CONFIG_PATH.read_text())

        # Patch VARIANT_CONFIG_FILE and ACTIVE_EXPERIMENT_FILE in orchestrator
        self._orig_variant = orchestrator.VARIANT_CONFIG_FILE
        self._orig_active = orchestrator.ACTIVE_EXPERIMENT_FILE
        orchestrator.VARIANT_CONFIG_FILE = self.fake_config
        orchestrator.ACTIVE_EXPERIMENT_FILE = self.tmpdir / "active_experiment.json"

    def teardown_method(self):
        orchestrator.VARIANT_CONFIG_FILE = self._orig_variant
        orchestrator.ACTIVE_EXPERIMENT_FILE = self._orig_active
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_challenger(self):
        return {
            "experiment_id": "exp-2026-03-13",
            "hypothesis": "Test loss aversion frame",
            "elements_changed": "hero_headline, cta_button_text",
            "challenger_copy": {
                "hero_headline": "Stop Losing Sales Between Market Days",
                "cta_button_text": "Get Your Free Storefront",
            },
        }

    def test_dry_run_does_not_write_variant_config(self):
        original_mtime = self.fake_config.stat().st_mtime
        challenger = self._make_challenger()
        orchestrator.phase_deploy(challenger, dry_run=True)
        new_mtime = self.fake_config.stat().st_mtime
        assert original_mtime == new_mtime, \
            "variant-config.json was written during dry run"

    def test_dry_run_does_not_create_active_experiment(self):
        challenger = self._make_challenger()
        orchestrator.phase_deploy(challenger, dry_run=True)
        assert not orchestrator.ACTIVE_EXPERIMENT_FILE.exists(), \
            "active_experiment.json was created during dry run"

    def test_live_deploy_writes_variant_config(self):
        challenger = self._make_challenger()
        orchestrator.phase_deploy(challenger, dry_run=False)
        written = json.loads(self.fake_config.read_text())
        assert written["experiment_id"] == "exp-2026-03-13"
        assert written["challenger"] is not None

    def test_live_deploy_saves_active_experiment(self):
        challenger = self._make_challenger()
        orchestrator.phase_deploy(challenger, dry_run=False)
        assert orchestrator.ACTIVE_EXPERIMENT_FILE.exists()
        active = json.loads(orchestrator.ACTIVE_EXPERIMENT_FILE.read_text())
        assert active["experiment_id"] == "exp-2026-03-13"

    def test_cta_button_text_expanded_to_two_buttons(self):
        """cta_button_text in challenger_copy must be split into cta_button_1 and cta_button_2."""
        challenger = self._make_challenger()
        orchestrator.phase_deploy(challenger, dry_run=False)
        written = json.loads(self.fake_config.read_text())
        assert "cta_button_1" in written["challenger"]
        assert "cta_button_2" in written["challenger"]
        assert written["challenger"]["cta_button_1"] == "Get Your Free Storefront"
        assert written["challenger"]["cta_button_2"] == "Get Your Free Storefront"
        # Original cta_button_text key should not remain
        assert "cta_button_text" not in written["challenger"]


# ===========================================================================
# 7. JSON / markdown-fence stripping logic in phase_generate output handling
# ===========================================================================

class TestJsonFenceStripping:
    """
    Test the fence-stripping logic inline (it's embedded in phase_generate).
    We extract and test the logic directly to avoid calling Claude.
    """

    def _strip_fences(self, raw: str) -> str:
        """Mirror of the stripping logic in orchestrator.phase_generate."""
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            clean = clean.strip()
        return clean

    def test_clean_json_unchanged(self):
        raw = '{"key": "value"}'
        assert self._strip_fences(raw) == '{"key": "value"}'

    def test_json_fence_stripped(self):
        raw = '```json\n{"key": "value"}\n```'
        result = self._strip_fences(raw)
        assert result == '{"key": "value"}'
        assert json.loads(result) == {"key": "value"}

    def test_bare_fence_stripped(self):
        raw = '```\n{"key": "value"}\n```'
        result = self._strip_fences(raw)
        assert result == '{"key": "value"}'

    def test_fence_with_trailing_whitespace(self):
        raw = '```json\n{"key": "value"}\n```   '
        result = self._strip_fences(raw)
        assert json.loads(result) == {"key": "value"}

    def test_non_fence_content_unchanged(self):
        raw = '   {"a": 1, "b": 2}   '
        result = self._strip_fences(raw)
        assert json.loads(result) == {"a": 1, "b": 2}


# ===========================================================================
# 8. File structure checks
# ===========================================================================

class TestFileStructure:

    def test_orchestrator_exists(self):
        assert (ROOT / "orchestrator.py").exists()

    def test_ga4_client_exists(self):
        assert (ROOT / "ga4_client.py").exists()

    def test_requirements_txt_exists(self):
        assert (ROOT / "requirements.txt").exists()

    def test_claude_md_exists(self):
        assert (ROOT / "CLAUDE.md").exists()

    def test_config_baseline_exists(self):
        assert (ROOT / "config" / "baseline.md").exists()

    def test_config_page_elements_exists(self):
        assert (ROOT / "config" / "page-elements.md").exists()

    def test_data_resource_exists(self):
        assert (ROOT / "data" / "resource.md").exists()

    def test_data_active_experiment_exists(self):
        assert (ROOT / "data" / "active_experiment.json").exists()

    def test_data_variant_config_exists(self):
        assert (ROOT / "data" / "variant-config.json").exists()

    def test_results_learnings_exists(self):
        assert (ROOT / "results" / "learnings.md").exists()

    def test_results_experiments_dir_exists(self):
        assert (ROOT / "results" / "experiments").is_dir()

    def test_ab_test_js_exists(self):
        assert (ROOT / "scripts" / "ab-test.js").exists()

    def test_github_workflow_exists(self):
        assert (ROOT / ".github" / "workflows" / "optimize.yml").exists()

    def test_env_exists(self):
        assert (ROOT / ".env").exists()

    def test_env_example_exists(self):
        assert (ROOT / ".env.example").exists()

    def test_gitignore_exists(self):
        assert (ROOT / ".gitignore").exists()


# ===========================================================================
# 9. Safety / configuration checks
# ===========================================================================

class TestSafetyConfig:

    def test_gitignore_excludes_env(self):
        gitignore = (ROOT / ".gitignore").read_text()
        assert ".env" in gitignore, ".gitignore does not exclude .env"

    def test_gitignore_excludes_service_account(self):
        gitignore = (ROOT / ".gitignore").read_text()
        assert "ga4-service-account.json" in gitignore, \
            ".gitignore does not exclude ga4-service-account.json"

    def test_prohibited_changes_dict_contains_pricing_key(self):
        assert "comparison_homegrown_1" in orchestrator.PROHIBITED_CHANGES
        assert orchestrator.PROHIBITED_CHANGES["comparison_homegrown_1"] == "$10/mo with everything included"

    def test_early_kill_constants_defined(self):
        assert orchestrator.EARLY_KILL_VISITORS == 50
        assert orchestrator.EARLY_KILL_RATIO == 0.5

    def test_min_experiment_days(self):
        assert orchestrator.MIN_EXPERIMENT_DAYS == 7

    def test_max_experiment_days(self):
        assert orchestrator.MAX_EXPERIMENT_DAYS == 21

    def test_min_visitors_per_arm(self):
        assert orchestrator.MIN_VISITORS_PER_ARM == 100

    def test_workflow_references_anthropic_secret(self):
        yml = (ROOT / ".github" / "workflows" / "optimize.yml").read_text()
        assert "ANTHROPIC_API_KEY" in yml
        assert "secrets.ANTHROPIC_API_KEY" in yml

    def test_workflow_references_ga4_secret(self):
        yml = (ROOT / ".github" / "workflows" / "optimize.yml").read_text()
        assert "GA4_SERVICE_ACCOUNT_JSON" in yml
        assert "secrets.GA4_SERVICE_ACCOUNT_JSON" in yml

    def test_workflow_uses_python_312(self):
        yml = (ROOT / ".github" / "workflows" / "optimize.yml").read_text()
        assert '"3.12"' in yml or "'3.12'" in yml or "3.12" in yml

    def test_workflow_runs_orchestrator(self):
        yml = (ROOT / ".github" / "workflows" / "optimize.yml").read_text()
        assert "python orchestrator.py" in yml

    def test_ab_test_js_fails_silently(self):
        js = (ROOT / "scripts" / "ab-test.js").read_text()
        assert ".catch" in js, "ab-test.js has no .catch() for graceful degradation"

    def test_ab_test_js_checks_experiment_id_before_swapping(self):
        js = (ROOT / "scripts" / "ab-test.js").read_text()
        assert "experiment_id" in js, "ab-test.js does not check experiment_id"

    def test_ab_test_js_cookie_assignment(self):
        js = (ROOT / "scripts" / "ab-test.js").read_text()
        assert "setCookie" in js
        assert "getCookie" in js

    def test_ab_test_js_ga4_tagging(self):
        js = (ROOT / "scripts" / "ab-test.js").read_text()
        assert "hg_variant" in js
        assert "gtag" in js

    def test_ab_test_js_resets_on_new_experiment(self):
        js = (ROOT / "scripts" / "ab-test.js").read_text()
        assert "hg_experiment_id" in js, \
            "ab-test.js does not reset variant assignment when experiment changes"

    def test_requirements_includes_google_analytics_data(self):
        req = (ROOT / "requirements.txt").read_text()
        assert "google-analytics-data" in req

    def test_requirements_includes_anthropic(self):
        req = (ROOT / "requirements.txt").read_text()
        assert "anthropic" in req

    def test_requirements_includes_python_dotenv(self):
        req = (ROOT / "requirements.txt").read_text()
        assert "python-dotenv" in req


# ===========================================================================
# 10. Statistical edge-case sanity checks
# ===========================================================================

class TestStatisticalEdgeCases:

    def test_very_small_sample_not_significant(self):
        # 1 click / 5 views vs 2 clicks / 5 views — never significant
        sig, z, p = orchestrator.is_significant(1, 5, 2, 5)
        assert sig is False

    def test_large_sample_small_effect_may_not_be_significant(self):
        # 10% vs 10.1%, even with 10,000 per arm — effect too tiny
        sig, z, p = orchestrator.is_significant(1000, 10000, 1010, 10000)
        assert sig is False, f"Tiny effect size should not be significant, p={p}"

    def test_100_percent_vs_50_percent_large_n(self):
        # 100% vs 50% with decent N — obviously significant
        # challenger at 100%, baseline at 50% — challenger clearly wins
        sig, z, p = orchestrator.is_significant(100, 200, 200, 200)
        assert sig is True, f"100% vs 50% should be highly significant, p={p}"

    def test_p_value_monotonically_decreases_with_larger_n(self):
        """Larger sample size with same effect → lower p-value."""
        _, _, p_small = orchestrator.is_significant(10, 100, 15, 100)
        _, _, p_large = orchestrator.is_significant(100, 1000, 150, 1000)
        assert p_large <= p_small, \
            f"p-value should decrease with larger n: {p_small} -> {p_large}"

    def test_z_score_magnitude_increases_with_effect_size(self):
        """Larger effect size → larger |z|."""
        _, z_small, _ = orchestrator.is_significant(10, 200, 15, 200)   # 5% effect
        _, z_large, _ = orchestrator.is_significant(10, 200, 30, 200)   # 20% effect
        assert abs(z_large) > abs(z_small)


# ===========================================================================
# RUNNER
# ===========================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
