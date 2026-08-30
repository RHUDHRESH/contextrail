import type { AgentId } from "./types";

/* ------------------------------------------------------------------ *
 * The specialist registry. Routing is capability-based: an action
 * declares the capability it needs, and the agent that owns that
 * capability receives the capsule. Adding an agent is a data change.
 * ------------------------------------------------------------------ */

export type AgentDef = {
  id: AgentId;
  name: string;
  owner: string;
  capabilities: string[];
  tools: string[];
  /** Shown on the handoff graph. */
  accent: "hr" | "it" | "security" | "support" | "finance" | "engineering";
  brief: string;
};

export const AGENTS: Record<AgentId, AgentDef> = {
  HR_AGENT: {
    id: "HR_AGENT",
    name: "HR Agent",
    owner: "People Operations",
    capabilities: ["worker_records", "paperwork_verification", "onboarding_orchestration", "offboarding_orchestration"],
    tools: ["hris.read_worker", "hris.verify_paperwork", "linear.create_checklist"],
    accent: "hr",
    brief: "Owns worker identity, employment classification, and the onboarding contract.",
  },
  IT_PROVISIONING_AGENT: {
    id: "IT_PROVISIONING_AGENT",
    name: "IT Provisioning Agent",
    owner: "IT Operations",
    capabilities: ["asset_allocation", "identity_provisioning", "ticketing", "device_management"],
    tools: ["freshservice.create_ticket", "freshservice.reserve_asset", "slack.invite_guest", "mdm.assign_device"],
    accent: "it",
    brief: "Allocates hardware, opens service tickets, and provisions day-one identity.",
  },
  SECURITY_AGENT: {
    id: "SECURITY_AGENT",
    name: "Security Agent",
    owner: "Security Engineering",
    capabilities: ["access_review", "privilege_grant", "credential_rotation", "risk_assessment"],
    tools: ["github.request_access", "security.open_review", "vault.rotate_credential"],
    accent: "security",
    brief: "Reviews privileged grants and holds the approval of record for third-party access.",
  },
  SUPPORT_AGENT: {
    id: "SUPPORT_AGENT",
    name: "Support Agent",
    owner: "Customer Support",
    capabilities: ["customer_context", "incident_lookup", "eligibility_assessment", "customer_comms"],
    tools: ["crm.read_account", "freshservice.read_incident", "freshservice.create_ticket"],
    accent: "support",
    brief: "Assembles customer and incident context and judges remedy eligibility.",
  },
  FINANCE_AGENT: {
    id: "FINANCE_AGENT",
    name: "Finance Agent",
    owner: "Revenue Operations",
    capabilities: ["billing_adjustment", "credit_issuance", "spend_approval"],
    tools: ["billing.apply_credit", "freshservice.create_ticket"],
    accent: "finance",
    brief: "Applies billing adjustments and holds spend authority above threshold.",
  },
  ENGINEERING_AGENT: {
    id: "ENGINEERING_AGENT",
    name: "Engineering Agent",
    owner: "Platform Engineering",
    capabilities: ["repository_management", "environment_setup"],
    tools: ["github.add_collaborator", "linear.create_project"],
    accent: "engineering",
    brief: "Handles repository membership and developer environment scaffolding.",
  },
};

/** Pick the agent that owns a capability; falls back to the entry agent. */
export function routeCapability(capability: string, fallback: AgentId): AgentId {
  const hit = Object.values(AGENTS).find((a) => a.capabilities.includes(capability));
  return hit?.id ?? fallback;
}

export const AGENT_ORDER: AgentId[] = [
  "HR_AGENT",
  "IT_PROVISIONING_AGENT",
  "SECURITY_AGENT",
  "ENGINEERING_AGENT",
  "SUPPORT_AGENT",
  "FINANCE_AGENT",
];
