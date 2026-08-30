import type { Evidence } from "./types";

/* ------------------------------------------------------------------ *
 * Facts are the typed projection of raw evidence that policy rules
 * read. Keeping extraction here means a policy never has to know which
 * system a value came from — only that it is present and cited.
 * ------------------------------------------------------------------ */

export type Facts = {
  employmentType: string | null;
  subjectName: string | null;
  workerId: string | null;
  managerName: string | null;
  startDate: string | null;
  sowEndDate: string | null;
  ndaSigned: boolean | null;
  sowCountersigned: boolean | null;
  sowRepositories: string[];
  requestedRepositories: string[];
  productionRepositories: string[];
  contractorLaptopsAvailable: number | null;
  standardLaptopsAvailable: number | null;
  customerName: string | null;
  customerTier: string | null;
  customerMrr: number | null;
  contractHasRefundClause: boolean | null;
  incidentId: string | null;
  incidentSeverity: string | null;
  incidentHours: number | null;
  slaBreached: boolean | null;
  creditRatePerDay: number | null;
  creditCapRatio: number | null;
  computedCreditUsd: number | null;
  requestsCashRefund: boolean;
  requestsWriteAccess: boolean;
  approvers: Record<string, string>;
  citations: Record<string, string>;
};

const get = <T,>(ev: Evidence[], id: string, path: string): T | null => {
  const e = ev.find((x) => x.id === id);
  if (!e?.data) return null;
  const v = path.split(".").reduce<unknown>((acc, key) => {
    if (acc === null || typeof acc !== "object") return null;
    return (acc as Record<string, unknown>)[key];
  }, e.data);
  return (v ?? null) as T | null;
};

export function extractFacts(evidence: Evidence[], rawRequest: string): Facts {
  const cite: Record<string, string> = {};
  const mark = (key: string, id: string, value: unknown) => {
    if (value !== null && value !== undefined) cite[key] = id;
    return value;
  };

  const repoRegistry = get<{ name: string; tags: string[] }[]>(evidence, "gh_repos", "repos") ?? [];
  const sowRepos = get<string[]>(evidence, "hris_priya", "sow_repositories") ?? [];
  const text = rawRequest.toLowerCase();
  // Only repositories the request actually names. Conflating these with
  // the SOW list would hide the case this policy exists to catch: a
  // request for a repository the engagement never covered.
  const requestedRepos = repoRegistry.filter((r) => text.includes(r.name.split("/")[1])).map((r) => r.name);

  const tier = get<string>(evidence, "crm_meridian", "tier");
  const mrr = get<number>(evidence, "crm_meridian", "mrr_usd");
  const hours = get<number>(evidence, "fs_inc_2481", "duration_hours");
  const tierMatrix = evidence.find((e) => e.id === "crm_tier_matrix")?.data as
    | Record<string, { credit_rate_per_day: number; cap: number }>
    | undefined;
  const rate = tier && tierMatrix?.[tier] ? tierMatrix[tier].credit_rate_per_day : null;
  const cap = tier && tierMatrix?.[tier] ? tierMatrix[tier].cap : null;

  let credit: number | null = null;
  if (rate !== null && cap !== null && mrr !== null && hours !== null) {
    const days = Math.floor(hours / 24);
    credit = Math.min(mrr * rate * days, mrr * cap);
    credit = Math.round(credit);
  }

  const facts: Facts = {
    employmentType: mark("employmentType", "hris_priya", get<string>(evidence, "hris_priya", "employment_type")) as string | null,
    subjectName: mark("subjectName", "hris_priya", get<string>(evidence, "hris_priya", "name")) as string | null,
    workerId: get<string>(evidence, "hris_priya", "worker_id"),
    managerName: mark("managerName", "hris_priya", get<string>(evidence, "hris_priya", "manager")) as string | null,
    startDate: mark("startDate", "hris_priya", get<string>(evidence, "hris_priya", "start_date")) as string | null,
    sowEndDate: get<string>(evidence, "hris_priya", "sow_end_date"),
    ndaSigned: get<boolean>(evidence, "hris_priya", "nda_signed"),
    sowCountersigned: get<boolean>(evidence, "hris_priya", "sow_countersigned"),
    sowRepositories: sowRepos,
    requestedRepositories: requestedRepos,
    productionRepositories: mark(
      "productionRepositories",
      "gh_repos",
      repoRegistry.filter((r) => r.tags.includes("production")).map((r) => r.name),
    ) as string[],
    contractorLaptopsAvailable: mark("contractorLaptopsAvailable", "fs_asset_pool", get<number>(evidence, "fs_asset_pool", "available")) as number | null,
    standardLaptopsAvailable: get<number>(evidence, "fs_asset_pool", "standard_pool_available"),
    customerName: mark("customerName", "crm_meridian", get<string>(evidence, "crm_meridian", "name")) as string | null,
    customerTier: mark("customerTier", "crm_meridian", tier) as string | null,
    customerMrr: mrr,
    contractHasRefundClause: mark("contractHasRefundClause", "crm_meridian", get<boolean>(evidence, "crm_meridian", "contract_has_refund_clause")) as boolean | null,
    incidentId: mark("incidentId", "fs_inc_2481", get<string>(evidence, "fs_inc_2481", "id")) as string | null,
    incidentSeverity: get<string>(evidence, "fs_inc_2481", "severity"),
    incidentHours: hours,
    slaBreached: mark("slaBreached", "fs_inc_2481", get<boolean>(evidence, "fs_inc_2481", "sla_breached")) as boolean | null,
    creditRatePerDay: rate,
    creditCapRatio: cap,
    computedCreditUsd: credit,
    requestsCashRefund: /\brefund\b|money back|cash back/.test(text),
    requestsWriteAccess: /\bwrite\b|\bpush\b|\bcommit\b|\bmerge\b|\badmin\b|\bmaintainer\b/.test(text),
    approvers: (evidence.find((e) => e.id === "hris_approvers")?.data as Record<string, string>) ?? {
      security_on_call: "Security on-call",
      finance_approver: "Finance approver",
      vp_finance: "VP Finance",
      it_provisioning_lead: "IT Provisioning lead",
    },
    citations: cite,
  };

  return facts;
}
