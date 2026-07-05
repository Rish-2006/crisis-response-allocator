/**
 * official_registry_tool.ts
 * =========================
 * MCP tool that queries a mock "official source" database simulating
 * FEMA / Red Cross / government feeds for cross-verification of claims.
 *
 * Returns STRUCTURED, TYPED responses so PlannerAgent can programmatically
 * compare claim vs. official record and compute a confidence delta.
 *
 * The official registry is the authoritative ground truth — if a claim
 * cannot be corroborated here, its confidence score takes a major hit.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Response types
// ---------------------------------------------------------------------------

export interface OfficialRecordItem {
  agency: string;
  confirmed: boolean;
  severity: string;
  casualties: number;
  affected_population: number;
  resource_needs: string[];
  timestamp: string;
  reference_id: string;
  location: string;
  incident_type: string;
}

export interface OfficialRegistryResponse {
  query_location: string;
  query_incident_type: string;
  total_records: number;
  records: OfficialRecordItem[];
}

// ---------------------------------------------------------------------------
// Input schema (Zod)
// ---------------------------------------------------------------------------

export const officialRegistryInputSchema = {
  location: z.string().describe("Geographic location to look up in the official registry"),
  incident_type: z.string().describe("Type of incident (e.g. 'flood', 'earthquake', 'wildfire', 'chemical_spill')"),
  date_range: z.string().optional().describe("Optional date range filter in ISO format (e.g. '2026-07-01/2026-07-05')"),
};

// ---------------------------------------------------------------------------
// Mock official database — authoritative ground truth
// ---------------------------------------------------------------------------

const OFFICIAL_RECORDS: OfficialRecordItem[] = [
  {
    agency: "FEMA",
    confirmed: true,
    severity: "high",
    casualties: 0,
    affected_population: 1200,
    resource_needs: ["water_units", "shelter_capacity", "medical_teams"],
    timestamp: "2026-07-04T09:00:00Z",
    reference_id: "FEMA-2026-FL-0847",
    location: "springfield",
    incident_type: "flood",
  },
  {
    agency: "Red Cross",
    confirmed: true,
    severity: "high",
    casualties: 2,
    affected_population: 1500,
    resource_needs: ["shelter_capacity", "water_units"],
    timestamp: "2026-07-04T11:00:00Z",
    reference_id: "RC-2026-SPR-1102",
    location: "springfield",
    incident_type: "flood",
  },
  {
    agency: "USGS",
    confirmed: true,
    severity: "moderate",
    casualties: 8,
    affected_population: 450,
    resource_needs: ["medical_teams", "shelter_capacity"],
    timestamp: "2026-07-04T06:30:00Z",
    reference_id: "USGS-2026-EQ-3291",
    location: "shelbyville",
    incident_type: "earthquake",
  },
  {
    agency: "State Emergency Management",
    confirmed: true,
    severity: "moderate",
    casualties: 12,
    affected_population: 500,
    resource_needs: ["medical_teams", "shelter_capacity", "water_units"],
    timestamp: "2026-07-04T07:00:00Z",
    reference_id: "SEM-2026-SHB-0044",
    location: "shelbyville",
    incident_type: "earthquake",
  },
  // Riverside chemical spill — NOT confirmed (to test unverified claim rejection)
  // Intentionally absent: if someone claims a chemical spill at Riverside,
  // the official registry has no matching record → low confidence.

  // Oakdale wildfire — NOT confirmed (to test misinformation rejection)
  // Intentionally absent: the BlogSpot claim about Oakdale is fabricated.
];

// ---------------------------------------------------------------------------
// Tool handler
// ---------------------------------------------------------------------------

export async function handleOfficialRegistry(args: {
  location: string;
  incident_type: string;
  date_range?: string;
}): Promise<OfficialRegistryResponse> {
  const locationLower = args.location.toLowerCase();
  const typeLower = args.incident_type.toLowerCase();

  const matchingRecords = OFFICIAL_RECORDS.filter((record) => {
    const locationMatch =
      record.location.includes(locationLower) ||
      locationLower.includes(record.location);
    const typeMatch =
      record.incident_type.includes(typeLower) ||
      typeLower.includes(record.incident_type);
    return locationMatch && typeMatch;
  });

  return {
    query_location: args.location,
    query_incident_type: args.incident_type,
    total_records: matchingRecords.length,
    records: matchingRecords,
  };
}
