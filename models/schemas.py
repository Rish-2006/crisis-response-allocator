"""
Pydantic data models defining all typed JSON contracts for inter-agent
communication, tool responses, and audit logging.

Every field is explicitly typed so that agents can programmatically validate
handoff payloads rather than relying on free-text parsing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """Standardised severity levels aligned with FEMA incident typing."""
    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    UNKNOWN = "unknown"


class ResourceType(str, Enum):
    """Categories of allocatable disaster-response resources."""
    MEDICAL_TEAMS = "medical_teams"
    WATER_UNITS = "water_units"
    SHELTER_CAPACITY = "shelter_capacity"


# ---------------------------------------------------------------------------
# Raw ingestion
# ---------------------------------------------------------------------------

class RawReport(BaseModel):
    """An unprocessed disaster report scraped from news / social media."""
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str = Field(..., description="Origin of the report (e.g. 'twitter', 'reuters', 'local_news')")
    text: str = Field(..., description="Full raw text of the report")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp of ingestion",
    )
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# Claim extraction (PlannerAgent output, pre-verification)
# ---------------------------------------------------------------------------

class ExtractedClaim(BaseModel):
    """A single discrete claim parsed from a raw report."""
    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_report_id: str = Field(..., description="ID of the RawReport this claim was extracted from")
    location: str = Field(..., description="Geographic location of the incident")
    incident_type: str = Field(..., description="E.g. 'flood', 'earthquake', 'wildfire'")
    severity: Severity = Severity.UNKNOWN
    casualty_count: Optional[int] = Field(None, ge=0)
    resource_need: Optional[str] = None
    population_affected: Optional[int] = Field(None, ge=0)
    priority_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Verification priority — higher means verify first",
    )
    raw_text_excerpt: str = Field("", description="The verbatim excerpt backing this claim")


# ---------------------------------------------------------------------------
# Verification results
# ---------------------------------------------------------------------------

class WebSearchResult(BaseModel):
    """A single result returned by web_search_tool."""
    source: str
    title: str
    snippet: str
    timestamp: str
    credibility_score: float = Field(..., ge=0.0, le=1.0)


class OfficialRecord(BaseModel):
    """A single record returned by official_registry_tool."""
    agency: str
    confirmed: bool
    severity: str
    casualties: int = Field(..., ge=0)
    timestamp: str
    reference_id: str


class VerificationResult(BaseModel):
    """Cross-verification outcome for a single claim."""
    claim_id: str
    web_sources_found: int = 0
    web_sources: list[WebSearchResult] = Field(default_factory=list)
    official_match: bool = False
    official_records: list[OfficialRecord] = Field(default_factory=list)
    confidence_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Composite confidence: 0 = unverified, 1 = fully confirmed",
    )
    confidence_delta: float = Field(
        0.0,
        description="Gap between web-source confidence and official-source confidence",
    )
    provenance_chain: list[str] = Field(
        default_factory=list,
        description="Ordered list of evidence steps for auditability",
    )
    rejection_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Verified incidents (PlannerAgent → ExecutorAgent handoff)
# ---------------------------------------------------------------------------

class VerifiedIncident(BaseModel):
    """A claim that has passed cross-verification with provenance."""
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    claim: ExtractedClaim
    verification: VerificationResult
    verification_token: str = Field(
        default_factory=lambda: f"VT-{uuid.uuid4().hex[:16]}",
        description="Cryptographic-style token proving verification was performed",
    )
    verified_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class VerifiedIncidentSet(BaseModel):
    """Complete handoff payload from PlannerAgent to ExecutorAgent."""
    set_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_by: str = "PlannerAgent"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    incidents: list[VerifiedIncident] = Field(default_factory=list)
    rejected_claims: list[dict] = Field(
        default_factory=list,
        description="Claims that failed verification, with reasons",
    )
    injection_alerts: list["InjectionAlert"] = Field(
        default_factory=list,
        description="Any prompt-injection attempts detected during verification",
    )
    reasoning_trace: list[str] = Field(
        default_factory=list,
        description="Step-by-step reasoning log for judge auditability",
    )


# ---------------------------------------------------------------------------
# Resource allocation (ExecutorAgent)
# ---------------------------------------------------------------------------

class ResourcePool(BaseModel):
    """Available resource inventory for allocation."""
    medical_teams: int = Field(20, ge=0, description="Number of deployable medical teams")
    water_units: int = Field(500, ge=0, description="Water supply units (each serves ~100 people)")
    shelter_capacity: int = Field(2000, ge=0, description="Total shelter spots available")


class AllocationDecision(BaseModel):
    """A single resource allocation decision with full reasoning trace."""
    incident_id: str
    location: str
    severity: str
    population_affected: int = 0
    priority_rank: int = Field(..., description="1 = highest priority")
    medical_teams_allocated: int = 0
    water_units_allocated: int = 0
    shelter_allocated: int = 0
    percentage_of_request_met: float = Field(0.0, ge=0.0, le=1.0)
    reasoning_trace: list[str] = Field(
        default_factory=list,
        description="Step-by-step reasoning for this allocation",
    )
    rebalanced: bool = Field(False, description="Whether this allocation was adjusted in rebalance pass")


class RejectedIncident(BaseModel):
    """An incident the ExecutorAgent refused to act on."""
    incident_id: str
    reason: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class DispatchPlan(BaseModel):
    """Final output of the ExecutorAgent — the complete logistics plan."""
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_by: str = "ExecutorAgent"
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    allocations: list[AllocationDecision] = Field(default_factory=list)
    rejected_incidents: list[RejectedIncident] = Field(default_factory=list)
    resource_pool_initial: ResourcePool = Field(default_factory=ResourcePool)
    resource_pool_remaining: ResourcePool = Field(default_factory=ResourcePool)
    total_incidents_processed: int = 0
    total_incidents_rejected: int = 0
    reasoning_trace: list[str] = Field(
        default_factory=list,
        description="High-level reasoning log for the entire dispatch plan",
    )


# ---------------------------------------------------------------------------
# Security / injection detection
# ---------------------------------------------------------------------------

class InjectionAlert(BaseModel):
    """Audit record for a detected prompt-injection attempt."""
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = Field(..., description="Which tool returned the poisoned payload")
    detected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    matched_pattern: str = Field(..., description="The regex/rule that triggered detection")
    raw_payload_hash: str = Field(..., description="SHA-256 hash of the full raw payload for forensics")
    quarantined_fragment: str = Field(..., description="The exact text that was removed")
    severity: str = Field("HIGH", description="Alert severity: HIGH, CRITICAL")


class SanitizedResult(BaseModel):
    """Output of the injection guard — clean text plus any alerts."""
    clean_text: str = Field(..., description="Sanitised text safe for agent consumption")
    was_modified: bool = Field(False, description="True if any content was removed")
    injection_alerts: list[InjectionAlert] = Field(default_factory=list)
    quarantined_fragments: list[str] = Field(default_factory=list)
