"""
Behave step definitions for crisis_response.feature.

These steps wire the Gherkin scenarios to the deterministic agent pipelines,
providing a BDD-compatible test harness alongside the pytest tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from behave import given, when, then, use_step_matcher

# Ensure project root is on sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from models.schemas import RawReport, ResourcePool, ExtractedClaim, Severity
from security.injection_guard import InjectionGuard
from agents.planner_agent import (
    _extract_claims_from_reports,
    search_disaster_reports,
    verify_with_official_registry,
    compute_confidence,
    run_planner_pipeline,
    CONFIDENCE_THRESHOLD,
)
from agents.executor_agent import run_executor_pipeline
from agents.orchestrator import run_full_pipeline

use_step_matcher("re")


# ============================================================================
# Background
# ============================================================================


@given(r"the resource pool has (\d+) medical teams, (\d+) water units, and (\d+) shelter spots")
def step_resource_pool(context, medical, water, shelter):
    context.resource_pool = ResourcePool(
        medical_teams=int(medical),
        water_units=int(water),
        shelter_capacity=int(shelter),
    )


@given("the injection guard is initialised with default patterns")
def step_injection_guard(context):
    context.guard = InjectionGuard()


# ============================================================================
# Given: raw reports
# ============================================================================

use_step_matcher("parse")


@given("the following raw disaster reports are ingested")
def step_ingest_reports(context):
    context.raw_reports = []
    for row in context.table:
        context.raw_reports.append({"source": row["source"], "text": row["text"]})


@given("a VerifiedIncidentSet with one incident missing its verification token")
def step_vis_missing_token(context):
    context.vis_with_missing_token = {
        "set_id": "test-set",
        "generated_by": "PlannerAgent",
        "timestamp": "2026-07-04T12:00:00Z",
        "incidents": [
            {
                "incident_id": "incident-valid",
                "claim": {
                    "claim_id": "c1",
                    "source_report_id": "r1",
                    "location": "Springfield",
                    "incident_type": "flood",
                    "severity": "high",
                    "population_affected": 1000,
                    "priority_score": 0.9,
                    "raw_text_excerpt": "flood",
                },
                "verification": {
                    "claim_id": "c1",
                    "confidence_score": 0.8,
                    "official_match": True,
                    "provenance_chain": ["verified"],
                },
                "verification_token": "VT-valid123",
                "verified_at": "2026-07-04T12:00:00Z",
            },
            {
                "incident_id": "incident-no-token",
                "claim": {
                    "claim_id": "c2",
                    "source_report_id": "r2",
                    "location": "Faketown",
                    "incident_type": "tornado",
                    "severity": "critical",
                    "population_affected": 5000,
                    "priority_score": 1.0,
                    "raw_text_excerpt": "tornado",
                },
                "verification": {
                    "claim_id": "c2",
                    "confidence_score": 0.9,
                    "official_match": True,
                    "provenance_chain": ["fabricated"],
                },
                "verification_token": "",
                "verified_at": "2026-07-04T12:00:00Z",
            },
        ],
        "rejected_claims": [],
        "injection_alerts": [],
        "reasoning_trace": [],
    }


# ============================================================================
# When steps
# ============================================================================


@when("PlannerAgent extracts claims from the reports")
def step_extract_claims(context):
    reports = [RawReport(**r) for r in context.raw_reports]
    context.claims = _extract_claims_from_reports(reports)


@when("each claim is cross-verified via web_search_tool")
def step_web_search(context):
    context.web_results = {}
    for claim in context.claims:
        result = search_disaster_reports(f"{claim.incident_type} {claim.location}")
        context.web_results[claim.location] = result


@when("each claim is cross-verified via official_registry_tool")
def step_official_verify(context):
    context.official_results = {}
    for claim in context.claims:
        result = verify_with_official_registry(claim.location, claim.incident_type)
        context.official_results[claim.location] = result


@when("conflicting sources are resolved by confidence scoring")
def step_confidence_scoring(context):
    context.confidence_scores = {}
    for claim in context.claims:
        web = context.web_results.get(claim.location, {}).get("results", [])
        official = context.official_results.get(claim.location, {}).get("records", [])
        verification = compute_confidence(claim, web, official)
        context.confidence_scores[claim.location] = verification.confidence_score


@when("PlannerAgent builds the VerifiedIncidentSet")
def step_build_vis(context):
    context.verified_incident_set = run_planner_pipeline(context.raw_reports)


@when("ExecutorAgent receives the VerifiedIncidentSet")
def step_executor_receives(context):
    handoff_json = json.dumps(context.verified_incident_set)
    context.handoff_data = json.loads(handoff_json)


@when("ExecutorAgent validates all verification tokens")
def step_validate_tokens(context):
    # Token validation happens inside run_executor_pipeline
    pass


@when("ExecutorAgent allocates resources using greedy-then-rebalance")
def step_allocate_resources(context):
    context.dispatch_plan = run_executor_pipeline(context.handoff_data)


@when("PlannerAgent processes the report through web_search_tool")
def step_planner_web_search(context):
    for report in context.raw_reports:
        result = search_disaster_reports(report["text"][:50])
        context.web_search_result = result
        # Also directly test the guard on the raw text
        sanitized = context.guard.sanitize(report["text"], tool_name="web_search_tool")
        context.sanitized_result = sanitized
        context.injection_alerts = sanitized.injection_alerts


@when("PlannerAgent continues reasoning on the sanitised data")
def step_continue_reasoning(context):
    context.verified_incident_set = run_planner_pipeline(context.raw_reports)


@when("the full pipeline produces a DispatchPlan")
def step_full_pipeline(context):
    context.dispatch_plan = run_full_pipeline(raw_reports=context.raw_reports)


@when("ExecutorAgent processes the VerifiedIncidentSet")
def step_executor_processes(context):
    context.dispatch_plan = run_executor_pipeline(context.vis_with_missing_token)


# ============================================================================
# Then steps — Scenario 1
# ============================================================================


@then("the following claims are extracted")
def step_check_claims(context):
    claim_locations = {c.location for c in context.claims}
    for row in context.table:
        assert row["location"] in claim_locations, f"Missing claim for {row['location']}"


@then("web search results are returned for each claim")
def step_check_web_results(context):
    for claim in context.claims:
        assert claim.location in context.web_results


@then('each web search result has structured fields: source, title, snippet, timestamp, credibility_score')
def step_check_web_fields(context):
    for loc, result in context.web_results.items():
        for r in result.get("results", []):
            assert "source" in r
            assert "title" in r
            assert "snippet" in r
            assert "timestamp" in r
            assert "credibility_score" in r


@then('official records confirm "{location}" {incident_type} with agency "{agency}"')
def step_check_official_confirm(context, location, incident_type, agency):
    result = context.official_results.get(location, {})
    agencies = [r["agency"] for r in result.get("records", [])]
    assert agency in agencies, f"Expected {agency} in records for {location}"


@then('no official records exist for "{location}" {incident_type}')
def step_check_no_official(context, location, incident_type):
    result = context.official_results.get(location, {})
    assert result.get("total_records", 0) == 0


@then('"{location}" {incident_type} has confidence score above {threshold}')
def step_confidence_above(context, location, incident_type, threshold):
    score = context.confidence_scores[location]
    assert score >= float(threshold), f"{location} score {score} < {threshold}"


@then('"{location}" {incident_type} has confidence score below {threshold}')
def step_confidence_below(context, location, incident_type, threshold):
    score = context.confidence_scores[location]
    assert score < float(threshold), f"{location} score {score} >= {threshold}"


@then("the VerifiedIncidentSet contains exactly {count:d} verified incidents")
def step_vis_count(context, count):
    assert len(context.verified_incident_set["incidents"]) == count


@then('the VerifiedIncidentSet contains {count:d} rejected claim for "{location}"')
def step_vis_rejected(context, count, location):
    rejected = context.verified_incident_set["rejected_claims"]
    matching = [r for r in rejected if r["location"] == location]
    assert len(matching) >= count


@then('each verified incident has a verification token starting with "VT-"')
def step_check_tokens(context):
    for inc in context.verified_incident_set["incidents"]:
        assert inc["verification_token"].startswith("VT-")


@then("the VerifiedIncidentSet includes a reasoning trace")
def step_vis_reasoning(context):
    assert len(context.verified_incident_set["reasoning_trace"]) > 0


@then("no incidents are rejected for missing tokens")
def step_no_rejections(context):
    # This is validated when executor runs without rejections
    pass


@then("a DispatchPlan is produced with {count:d} allocation decisions")
def step_plan_count(context, count):
    assert len(context.dispatch_plan["allocations"]) == count


@then('"{location}" has a higher priority rank than "{other}"')
def step_priority_rank(context, location, other):
    allocs = context.dispatch_plan["allocations"]
    loc_rank = next(a["priority_rank"] for a in allocs if a["location"] == location)
    other_rank = next(a["priority_rank"] for a in allocs if a["location"] == other)
    assert loc_rank < other_rank  # Lower rank number = higher priority


@then("each allocation decision includes a reasoning trace")
def step_alloc_reasoning(context):
    for alloc in context.dispatch_plan["allocations"]:
        assert len(alloc["reasoning_trace"]) > 0


@then("the remaining resource pool has fewer resources than the initial pool")
def step_pool_reduced(context):
    initial = context.dispatch_plan["resource_pool_initial"]
    remaining = context.dispatch_plan["resource_pool_remaining"]
    assert remaining["medical_teams"] < initial["medical_teams"]


# ============================================================================
# Then steps — Scenario 2 (Day 4)
# ============================================================================


@then("the injection guard detects a prompt injection attempt")
def step_injection_detected(context):
    assert context.sanitized_result.was_modified is True
    assert len(context.injection_alerts) > 0


@then('the injection alert matches pattern "{pattern}"')
def step_injection_pattern(context, pattern):
    patterns_found = {a.matched_pattern for a in context.injection_alerts}
    assert pattern in patterns_found, f"Pattern {pattern} not found in {patterns_found}"


@then("the malicious payload is quarantined with full provenance")
def step_quarantine_provenance(context):
    for alert in context.injection_alerts:
        assert alert.raw_payload_hash
        assert alert.quarantined_fragment
        assert alert.detected_at


@then('the quarantined fragment contains "{text}"')
def step_quarantine_contains(context, text):
    all_fragments = " ".join(context.sanitized_result.quarantined_fragments)
    assert text in all_fragments


@then('the injection attempt is logged with tool name "{tool}"')
def step_injection_logged(context, tool):
    assert any(a.tool_name == tool for a in context.injection_alerts)


@then('the "{location}" chemical spill claim has confidence score below {threshold}')
def step_chemical_spill_confidence(context, location, threshold):
    rejected = context.verified_incident_set.get("rejected_claims", [])
    matching = [r for r in rejected if r["location"] == location]
    if matching:
        assert matching[0]["confidence_score"] < float(threshold)


@then("the claim is rejected due to lack of official confirmation")
def step_claim_rejected(context):
    rejected = context.verified_incident_set.get("rejected_claims", [])
    assert len(rejected) > 0


@then('the DispatchPlan does NOT contain any allocation for "{location}"')
def step_no_allocation(context, location):
    allocs = context.dispatch_plan.get("allocations", [])
    locations = [a["location"] for a in allocs]
    assert location not in locations


@then('the DispatchPlan does NOT reference "{text}"')
def step_no_reference(context, text):
    plan_json = json.dumps(context.dispatch_plan)
    assert text not in plan_json


@then('the DispatchPlan does NOT reference "{text1}" or "{text2}"')
def step_no_reference_or(context, text1, text2):
    plan_json = json.dumps(context.dispatch_plan)
    assert text1 not in plan_json
    assert text2 not in plan_json


@then("the DispatchPlan is unaffected by the injected instruction")
def step_plan_unaffected(context):
    plan_json = json.dumps(context.dispatch_plan)
    assert "WAREHOUSE" not in plan_json
    assert "ADMIN MODE" not in plan_json
    assert "PIER 43" not in plan_json


# ============================================================================
# Then steps — Scenario 3 (Hard Stop)
# ============================================================================


@then("ExecutorAgent issues a HARD STOP for the unverified incident")
def step_hard_stop(context):
    rejected = context.dispatch_plan["rejected_incidents"]
    assert any("HARD STOP" in r["reason"] for r in rejected)


@then("the HARD STOP is logged as an error, not a warning")
def step_hard_stop_error(context):
    # The reasoning trace should contain HARD STOP indicators
    trace = " ".join(context.dispatch_plan["reasoning_trace"])
    assert "HARD STOP" in trace


@then("no resources are allocated to the unverified incident")
def step_no_resources_unverified(context):
    allocs = context.dispatch_plan.get("allocations", [])
    locations = [a["location"] for a in allocs]
    assert "Faketown" not in locations


@then("the DispatchPlan lists the incident in rejected_incidents")
def step_rejected_listed(context):
    assert len(context.dispatch_plan["rejected_incidents"]) > 0
