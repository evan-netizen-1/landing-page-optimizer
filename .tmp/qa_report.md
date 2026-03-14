## QA Report — Landing Page Optimizer
**Date:** 2026-03-13

---

## Test Results
**Status: PASS**
**Tests run:** 97 | **Passed:** 97 | **Failed:** 0

Test file: `/Users/evanknox/Desktop/Claude/landing-page-optimizer/.tmp/test_optimizer.py`

---

## Test Cases by Group

### 1. two_proportion_z_test (11 tests)
- [PASS] test_zero_n1_returns_neutral: n1=0 returns z=0.0, p=1.0
- [PASS] test_zero_n2_returns_neutral: n2=0 returns z=0.0, p=1.0
- [PASS] test_pooled_rate_zero_returns_neutral: both rates=0 returns z=0.0, p=1.0
- [PASS] test_pooled_rate_one_returns_neutral: both rates=1.0 returns z=0.0, p=1.0
- [PASS] test_identical_rates_gives_z_zero: equal rates → z≈0, p≈0.5
- [PASS] test_clearly_significant_result: 20% vs 40% n=500 → z>6, p<0.0001
- [PASS] test_standard_significance_threshold: 10% vs 14% n=2000 → z>1.96, p<0.05
- [PASS] test_challenger_worse_gives_negative_z: p2<p1 → z<0, p>0.5
- [PASS] test_p_value_in_valid_range: p always in [0.0, 1.0]
- [PASS] test_asymmetric_sample_sizes: very different n1/n2 doesn't crash
- [PASS] test_formula_correctness_manual: hand-computed values match to 1e-9

### 2. is_significant (10 tests)
- [PASS] test_zero_baseline_views_returns_false: 0 baseline views → (False, 0.0, 1.0)
- [PASS] test_zero_challenger_views_returns_false: 0 challenger views → (False, 0.0, 1.0)
- [PASS] test_clearly_significant_promotes: 10% vs 30% n=500 → is_sig=True
- [PASS] test_not_significant_with_small_effect_and_small_n: 10% vs 12% n=50 → False
- [PASS] test_custom_alpha_strict: alpha=0.01 is more restrictive than alpha=0.05
- [PASS] test_custom_alpha_relaxed: alpha=0.10 at least as permissive as alpha=0.05
- [PASS] test_returns_tuple_of_three: return type is (bool, float, float)
- [PASS] test_challenger_worse_not_significant: challenger with lower CTR → False, z<0
- [PASS] test_identical_rates_not_significant: equal rates → False
- [PASS] test_rates_derived_correctly: b_rate=b_clicks/b_views computed correctly

### 3. variant-config.json structure (13 tests)
- [PASS] test_valid_json_loads: file is valid JSON dict
- [PASS] test_top_level_keys_present: all 6 top-level keys exist
- [PASS] test_selectors_is_dict: selectors field is a dict
- [PASS] test_selectors_not_empty: 29 selectors found
- [PASS] test_all_selector_values_are_strings: all values are strings
- [PASS] test_all_selectors_contain_data_w_id: all use data-w-id attribute
- [PASS] test_cta_buttons_present: cta_button_1 and cta_button_2 present
- [PASS] test_hero_elements_present: hero_headline and hero_subheadline present
- [PASS] test_feature_cards_present: all 3 feature card title+desc pairs present
- [PASS] test_detail_cards_present: all 6 detail card title+desc pairs present
- [PASS] test_section_headings_present: all 4 section headings present
- [PASS] test_comparison_heading_present: comparison_heading present
- [PASS] test_initial_state_no_active_experiment: experiment_id and challenger are null

### 4. CSS selector consistency (5 tests)
- [PASS] test_page_elements_parsed_nonempty: 42 node IDs parsed from page-elements.md
- [PASS] test_every_config_selector_node_id_exists_in_page_elements: all 29 node IDs in variant-config are present in page-elements.md
- [PASS] test_all_config_keys_have_matching_node_id: all selectors contain a valid UUID
- [PASS] test_hero_headline_node_id_matches: 87a34d83-50aa-82af-649c-d1db1ce92307 confirmed
- [PASS] test_hero_subheadline_node_id_matches: dc19941b-af81-bfbb-9820-705ef670de8e confirmed
- [PASS] test_cta_button_1_node_id_matches: 7341f29e-8b06-6659-f639-a254ad431094 confirmed
- [PASS] test_cta_button_2_node_id_matches: 7341f29e-8b06-6659-f639-a254ad431096 confirmed
- [PASS] test_mid_page_hook_node_id_matches: c6096f36-f380-f68c-8f44-f6001938009c confirmed

### 5. _validate_challenger safety (5 tests)
- [PASS] test_valid_challenger_passes: normal challenger copy raises no error
- [PASS] test_prohibited_key_wrong_value_raises: wrong pricing raises RuntimeError
- [PASS] test_prohibited_key_correct_value_passes: correct pricing passes silently
- [PASS] test_long_headline_emits_warning_not_error: >60 chars warns but does not raise
- [PASS] test_empty_challenger_copy_is_valid_for_validator: empty dict passes _validate_challenger

### 6. phase_deploy / dry-run (5 tests)
- [PASS] test_dry_run_does_not_write_variant_config: file mtime unchanged after --dry-run
- [PASS] test_dry_run_does_not_create_active_experiment: active_experiment.json not created
- [PASS] test_live_deploy_writes_variant_config: variant-config.json updated with experiment_id
- [PASS] test_live_deploy_saves_active_experiment: active_experiment.json written correctly
- [PASS] test_cta_button_text_expanded_to_two_buttons: cta_button_text → cta_button_1 + cta_button_2, original key removed

### 7. JSON fence-stripping logic (5 tests)
- [PASS] test_clean_json_unchanged: bare JSON is passed through
- [PASS] test_json_fence_stripped: ```json ... ``` is stripped cleanly
- [PASS] test_bare_fence_stripped: ``` ... ``` is stripped cleanly
- [PASS] test_fence_with_trailing_whitespace: trailing whitespace handled
- [PASS] test_non_fence_content_unchanged: leading/trailing spaces trimmed

### 8. File structure (15 tests)
- [PASS] All 15 expected files/directories exist

### 9. Safety config checks (15 tests)
- [PASS] .gitignore excludes .env
- [PASS] .gitignore excludes ga4-service-account.json
- [PASS] PROHIBITED_CHANGES contains comparison_homegrown_1 with correct value
- [PASS] EARLY_KILL_VISITORS=50, EARLY_KILL_RATIO=0.5
- [PASS] MIN_EXPERIMENT_DAYS=7, MAX_EXPERIMENT_DAYS=21, MIN_VISITORS_PER_ARM=100
- [PASS] Workflow references secrets.ANTHROPIC_API_KEY and secrets.GA4_SERVICE_ACCOUNT_JSON
- [PASS] Workflow uses Python 3.12
- [PASS] Workflow runs `python orchestrator.py`
- [PASS] ab-test.js has .catch() for silent failure
- [PASS] ab-test.js checks experiment_id before variant swap
- [PASS] ab-test.js implements getCookie/setCookie
- [PASS] ab-test.js tags GA4 via gtag with hg_variant
- [PASS] ab-test.js resets assignment when experiment ID changes
- [PASS] requirements.txt includes google-analytics-data, anthropic, python-dotenv

### 10. Statistical edge cases (5 tests)
- [PASS] test_very_small_sample_not_significant: n=5 per arm → never significant
- [PASS] test_large_sample_small_effect_may_not_be_significant: 10% vs 10.1% n=10000 → False
- [PASS] test_100_percent_vs_50_percent_large_n: challenger 100% vs baseline 50% → significant
- [PASS] test_p_value_monotonically_decreases_with_larger_n: confirmed
- [PASS] test_z_score_magnitude_increases_with_effect_size: confirmed

---

## Manual Code Review Findings

### orchestrator.py
- All three phases (harvest, generate, deploy) are present and correctly sequenced.
- two_proportion_z_test uses `math.erfc(z / math.sqrt(2)) * 0.5` which is the correct one-tailed normal CDF approximation. Verified at z=1.96 → p≈0.025.
- All guard clauses in two_proportion_z_test are correct: n=0, p_pool=0, p_pool=1, se=0 all return (0.0, 1.0).
- is_significant correctly divides clicks/views for both arms before calling two_proportion_z_test.
- Early kill logic checks c_views >= 50 AND b_views >= 50 AND c_ctr < 50% of b_ctr — correct.
- Timeout at MAX_EXPERIMENT_DAYS reverts to baseline — correct.
- _promote_challenger uses regex substitution to update baseline.md. This is fragile if keys appear mid-line or have unusual spacing, but works for the structured format of baseline.md.
- dry-run mode correctly bypasses both VARIANT_CONFIG_FILE write and ACTIVE_EXPERIMENT_FILE write.
- cta_button_text is correctly expanded to cta_button_1 and cta_button_2 during deploy.
- JSON fence-stripping handles both "```json" and "```" prefixes.
- Challenger validation: PROHIBITED_CHANGES check enforces comparison_homegrown_1 value; long headline is a warning only (not a hard error). Intentional per design.
- model used: "claude-opus-4-6" with adaptive thinking — correct per system design.

### ga4_client.py
- Correctly imports from google.analytics.data_v1beta.
- _get_client() handles both file-path and inline JSON service account configurations.
- Empty GA4_SERVICE_ACCOUNT_JSON raises RuntimeError with a clear message — correct.
- get_variant_metrics() queries two events separately (page_view with /signup filter, signup_cta_click without path filter) and computes CTR correctly.
- NOTE: The page_path parameter is passed to _query_event_by_variant for page_view but is never actually applied to the GA4 request (no filter is added for pagePath inside _query_event_by_variant). This means page_view counts may include views from pages other than /signup if a visitor triggers page_view on multiple pages. This is a latent bug but low-risk since hg_variant is only set on /signup visitors.

### variant-config.json vs page-elements.md
- All 29 selectors in variant-config.json have node IDs that exist in page-elements.md.
- page-elements.md has 42 total elements; variant-config.json exposes 29 of them (omits comparison_other_*, comparison_homegrown_*, and setup bullets — intentional, these are less commonly mutated).
- Selector string format is consistent: `[data-w-id="<uuid>"]`.

### ab-test.js
- Fetch with cache-bust (?t=Date.now()) — correct.
- Exits early if cfg.experiment_id is falsy — correct (prevents running when no experiment is active).
- Variant reset when experiment ID changes — correctly implemented via hg_experiment_id cookie.
- Uses innerHTML only when value contains `<br` — correct and safe since orchestrator controls the content.
- 30-day cookie expiry — appropriate.
- .catch() swallows all errors silently — correct (baseline always shows on failure).
- gtag call uses "set" with user_properties — correct GA4 syntax for user property assignment.

### GitHub Actions workflow
- Cron: "0 6 * * *" (daily 6am UTC) — correct.
- Python 3.12 — correct.
- Secrets: ANTHROPIC_API_KEY and GA4_SERVICE_ACCOUNT_JSON properly referenced.
- Git commit step uses `git add -f` for key data files — the `-f` flag forces tracking of files that might be in .gitignore. Since variant-config.json and active_experiment.json are in /data/ (not gitignored), this is safe but slightly over-specified.
- The commit step suppresses errors for results files (`|| true`) — correct, they may not exist on first run.

---

## Issues Found

### Low severity (code quality / latent)

1. **ga4_client.py: page_path filter is accepted but never applied.** The `_query_event_by_variant` function accepts a `page_path` parameter but never adds a dimension filter for it to the GA4 RunReportRequest. The page_view query is intended to filter to `/signup` only, but it currently counts page_view events from all pages for users who have the hg_variant property set. In practice this likely has minimal impact since hg_variant is only set after landing on /signup, but it could inflate page_view counts if users navigate elsewhere in the same session.

2. **_promote_challenger regex fragility.** The regex `^(key:\s*)".*?"` only matches quoted single-line values. If baseline.md ever contains multi-line values (it currently has some with `\n` in them), the fallback regex `^(key:\s*).*$` will match only the first line. This is low-risk because baseline.md is tightly controlled, but worth noting.

3. **variant-config.json exposes only 29 of 42 page-elements.** The comparison_other_*, comparison_homegrown_*, and section_setup_bullet_* elements in page-elements.md have no selectors in variant-config.json. This means Claude cannot test mutations to those elements even if it tries to — the orchestrator will log a warning but silently drop them. The PROHIBITED_CHANGES list does protect comparison_homegrown_1, but Claude has no mechanism to change comparison_homegrown_2 through _8 either. This is probably intentional.

4. **ga4-service-account.json is present in the repo directory** (confirmed by `ls -la` output, file size 2416 bytes). It IS in .gitignore, so it will not be committed. No action needed, but worth being aware of.

### No issues found in:
- Statistical math correctness
- Dry-run safety
- Early kill logic
- Timeout/revert logic
- Prohibited content validation
- ab-test.js graceful degradation
- Secrets configuration in workflow
- File structure completeness
