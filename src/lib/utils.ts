import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const SYSTEM_LABEL: Record<string, string> = {
  notion: "Notion",
  gdocs: "Google Docs",
  slack: "Slack",
  freshservice: "Freshservice",
  crm: "CRM",
  github: "GitHub",
  linear: "Linear",
  hris: "HRIS",
};

export const SYSTEM_COLOR: Record<string, string> = {
  notion: "var(--color-notion)",
  gdocs: "var(--color-gdocs)",
  slack: "var(--color-slack)",
  freshservice: "var(--color-freshservice)",
  crm: "var(--color-crm)",
  github: "var(--color-github)",
  linear: "var(--color-linear)",
  hris: "var(--color-hris)",
};

export const AGENT_COLOR: Record<string, string> = {
  HR_AGENT: "var(--color-hris)",
  IT_PROVISIONING_AGENT: "var(--color-freshservice)",
  SECURITY_AGENT: "var(--color-caution)",
  SUPPORT_AGENT: "var(--color-gdocs)",
  FINANCE_AGENT: "var(--color-crm)",
  ENGINEERING_AGENT: "var(--color-linear)",
};

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour12: false });
}
