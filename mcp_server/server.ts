/**
 * MCP Server — Crisis Response Verification Tools
 * =================================================
 * Registers two tools via the Model Context Protocol:
 *   1. web_search_tool   — searches for live/simulated disaster news reports
 *   2. official_registry_tool — queries the authoritative official database
 *
 * Uses stdio transport for local development (compatible with ADK's
 * MCPToolset). Structured, typed JSON responses throughout.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { webSearchInputSchema, handleWebSearch } from "./tools/web_search_tool.js";
import {
  officialRegistryInputSchema,
  handleOfficialRegistry,
} from "./tools/official_registry_tool.js";

// ---------------------------------------------------------------------------
// Server initialisation
// ---------------------------------------------------------------------------

const server = new McpServer({
  name: "crisis-response-verification",
  version: "1.0.0",
});

// ---------------------------------------------------------------------------
// Tool registration
// ---------------------------------------------------------------------------

server.tool(
  "web_search_tool",
  "Search for live or simulated news reports about a disaster event. " +
    "Returns structured results with source, title, snippet, timestamp, " +
    "and credibility score for each result.",
  webSearchInputSchema,
  async (args) => {
    const response = await handleWebSearch({
      query: args.query as string,
      max_results: (args.max_results as number) ?? 5,
    });
    return {
      content: [
        {
          type: "text" as const,
          text: JSON.stringify(response, null, 2),
        },
      ],
    };
  }
);

server.tool(
  "official_registry_tool",
  "Query the official disaster registry (simulated FEMA/Red Cross/government " +
    "feeds) to cross-verify claims. Returns structured records with agency, " +
    "confirmation status, severity, casualties, and reference ID.",
  officialRegistryInputSchema,
  async (args) => {
    const response = await handleOfficialRegistry({
      location: args.location as string,
      incident_type: args.incident_type as string,
      date_range: args.date_range as string | undefined,
    });
    return {
      content: [
        {
          type: "text" as const,
          text: JSON.stringify(response, null, 2),
        },
      ],
    };
  }
);

// ---------------------------------------------------------------------------
// Transport & startup
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // Log to stderr (stdout is reserved for MCP JSON-RPC)
  console.error("Crisis Response MCP Server running on stdio transport");
}

main().catch((error) => {
  console.error("Fatal error starting MCP server:", error);
  process.exit(1);
});
