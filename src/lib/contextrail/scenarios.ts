export type Scenario = {
  id: string;
  label: string;
  domain: string;
  request: string;
  requesterId: string;
  hook: string;
  proves: string;
};

export const SCENARIOS: Scenario[] = [
  {
    id: "contractor",
    label: "Contractor onboarding",
    domain: "HR → IT → Security",
    request: "Priya joins engineering on Monday. Give her everything she needs to start.",
    requesterId: "U-2201",
    hook: "One sentence, five systems, three agents, one thing that must not happen.",
    proves: "Blanket asks get decomposed, and the one forbidden action is refused with a citation.",
  },
  {
    id: "refund",
    label: "Refund after an outage",
    domain: "Support → Finance",
    request:
      "Meridian Freight wants a refund after the three-day telemetry outage. What do we owe them and can we action it?",
    requesterId: "U-3310",
    hook: "Same rail, different domain — nothing about it was built for onboarding.",
    proves: "The platform is infrastructure, not a single-workflow app.",
  },
  {
    id: "access",
    label: "Standalone access request",
    domain: "Security",
    request: "Grant Priya write access to the fleet-api repository so she can fix the ingest bug.",
    requesterId: "U-2201",
    hook: "A reasonable-sounding request that policy will not allow.",
    proves: "Governance holds even when the request comes from a manager with authority.",
  },
];

export function getScenario(id: string | null | undefined): Scenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}
