# Category and competitor research

Research date: 26 August 2026. Verified against live pages, not marketing copy. This is a positioning memo, not a feature scorecard.

## Executive conclusion

The credible position is **not** “other platforms cannot orchestrate agents, preserve context, or handle approvals.” Freshworks, Microsoft, Salesforce, and ServiceNow all advertise those capabilities.

ContextRail’s defensible wedge is narrower and now better sourced:

1. **MCP itself is becoming a stateless tool bus.** The 2026-07-28 MCP revision treats each `tools/call` as independently routable. The protocol will not carry your evidence, constraints, or refusals between calls. That contract has to live in an application layer. ContextRail is that layer.
2. **Freshworks MCP Gateway is a governed connector**, not an evidence contract. An independent write-up lists 28 inbound tools across tickets, assets, users, onboarding, catalog, knowledge, and workspaces. That is connector coverage. It is not subject-identity resolution, clause-level denial, or post-condition verification.
3. **Freshworks Agent Studio already orchestrates onboarding-style work.** Claiming “Freshworks cannot orchestrate” is false and will lose a Freshworks-sponsored room. ContextRail sits *on* that surface: the capsule, the terminal deny, the verify probe.

## Hackathon facts

Verified from the live Devpost listing on 26 August 2026:

| Fact | Live listing | Notes |
|---|---|---|
| Event | The Great Agent Hackathon, presented by TGPF 2026 | Freshworks title sponsor; ElevenLabs + Dodo Payments credits |
| Stage 1 deadline | **30 August 2026, 11:45pm IST** | A rules subpage and the Luma event page have also shown 25 August. Confirm on the live submit form before sending. |
| Team size | Exactly 2 people | “Team required: 2 to 2 members” |
| Stage 1 | Figma prototype **or** working demo + written submission + 1–2 min video + team bios | A working demo satisfies the prototype rule; Figma still helps judges who never run the app |
| Stage 2 | 25–26 September 2026, Bangalore, 24-hour overnight build + main-stage demo | Public repo + README required at Stage 2 |
| Track 1 | Customer & Employee Experience: agents on Freshworks Agent Studio, MCP, and multi-agent orchestration | Primary track. Contractor onboarding is the stated example family. |
| Track 2 | Platform Agent Skills & Knowledge: reusable skills, MCP integrations, Freshworks developer platform | Secondary alignment: 6 tools, 5 skills |
| Track 3 | AI-native Enterprise (open) | Do not submit here; the Freshworks fit is the point |
| Judging | Innovation, Technical Execution, Use of AI/Agentic Design, Relevance, Presentation/Demo, Potential Impact | Demo quality is a named criterion |
| Judges | Minakshi Khuntia (Senior Director of Product Management, Freshworks), Amrit Raj (Founder, Future Minds Institute) | Write for a product-and-platform audience |
| Gallery | Not published | Direct-submission competitor review is not possible yet |

Sources: [Devpost listing](https://the-great-agent-hackathon.devpost.com/), [Devpost rules](https://the-great-agent-hackathon.devpost.com/rules), [Luma](https://luma.com/b34nmre6).

## Freshworks surface — what is actually shipping

May 14 2026 (Refresh 2026, San Mateo):

- **Freddy AI Agent Studio** — no-code / pre-built domain agents, deployable into Slack, Teams, and portals. Official materials describe onboarding and payroll-style workflows that already cross HRIS systems (Workday, Rippling).
- **MCP Gateway** — inbound (external clients query Freshservice) and outbound (Freddy agents act in Atlassian, Notion, Linear, ClickUp). Official Freshservice docs: MCP is Beta / EAP, Enterprise plan, API key or OAuth. New commercial limits take effect 1 September 2026. Third-party write-ups also report inbound as Enterprise-only during EAP and outbound needing Agent Studio on Growth+.
- **Design choice:** tools wrap pre-approved logic. There is no arbitrary query surface. That is the correct security posture. It also means the gateway is a *catalog of verbs*, not a workflow memory.

Independent enumeration (eesel, 15 May 2026): 28 tools across tickets, assets, users/agents, onboarding/offboarding, service catalog, knowledge, workspaces. Treat 28 as a third-party count, not an official Freshworks number.

Sources: [Freshworks May 2026 launch](https://www.freshworks.com/theworks/company-news/may-2026-launch/), [Agent Studio press release (IR)](https://ir.freshworks.com/news/news-details/2026/Freshworks-Unveils-AI-Agent-Studio-in-Freshservice-to-Unlock-Service-Transformation-that-Drives-Compounding-Business-Growth/default.aspx), [Freshservice MCP EAP docs](https://support.freshservice.com/support/solutions/articles/50000012678-model-context-protocol-mcp-integration-in-freshservice-eap-), [SiliconANGLE, 14 May 2026](https://siliconangle.com/2026/05/14/freshworks-unveils-freddy-ai-agent-studio-mcp-gateway-freshservice/), [eesel MCP Gateway explained](https://www.eesel.ai/blog/freshworks-mcp-gateway-explained).

## Platform landscape

| Platform | Verified capability | Do not claim | ContextRail’s useful distinction |
|---|---|---|---|
| Freshworks | Agent Studio, inbound/outbound MCP, RBAC, onboarding-style agents | That Freshworks lacks orchestration or cross-department workflows | Portable evidence package, clause-level verdicts, terminal denials, post-condition verification as one visible contract sitting *on* MCP |
| Microsoft | Copilot Studio agent tools, deterministic workflows, MCP, advanced multi-stage approvals | That human-in-the-loop or multistep workflows are missing | The complete evidence/decision history is the handoff artifact, not a pile of workflow inputs |
| Salesforce | Agent Fabric / Agentforce: multi-agent orchestration, shared context, A2A/MCP, policies, traces, MCP Bridge | That shared context, protocols, or governance are unique | Policy applicability, terminal refusal, blockers, and verified operational state are the judge-visible story |
| ServiceNow | AI Control Tower: inventory, observe, govern, secure, Intelligent Approvals, MCP server lifecycle | That enterprise governance queues are novel | Evidence provenance, planning, denial semantics, and verification join in one operator workflow |

Sources: [Microsoft agent tools](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/tools-available), [Microsoft advanced approvals](https://learn.microsoft.com/en-us/microsoft-copilot-studio/flows-advanced-approvals), [Microsoft MCP](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-add-components-to-agent), [Salesforce Agent Fabric](https://www.salesforce.com/news/stories/agent-fabric-control-plane-announcement/), [Salesforce multi-agent orchestration](https://www.salesforce.com/agentforce/multi-agent-orchestration/), [ServiceNow Control Tower](https://www.servicenow.com/products/ai-control-tower.html), [ServiceNow Knowledge 2026 expansion](https://newsroom.servicenow.com/press-releases/details/2026/ServiceNow-expands-AI-Control-Tower-to-discover-observe-govern-secure-and-measure-AI-deployed-across-any-system-in-the-enterprise/default.aspx).

## Protocol fact that helps us

The official MCP `2026-07-28` specification retires `initialize` / `initialized` and the `Mcp-Session-Id` header. Every request is self-describing. Any call can land on any server instance behind a round-robin load balancer.

The spec authors say this explicitly: dropping the protocol session does **not** force the application to be stateless. If you need state across calls, **mint an explicit handle from a tool and have the model pass it back as an argument**. That is a better pattern than hiding session state in the transport.

ContextRail’s Context Capsule is that handle, structured: request, resolved subject, citations, constraints, prior decisions, blockers, and verification results, moved by value.

Primary source: [MCP 2026-07-28 specification announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/). Also: [Google on stateless MCP](https://developers.googleblog.com/en/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/).

## Adjacent hackathon work

`Pramaan` (published Devpost) focuses on Proof-of-Authority, delegation identity, policy validation, and red-team checks. Overlaps the broad governance category; not confirmed as an entrant here. Differentiate on operational knowledge-to-action: correct subject, evidence across specialists, hold or terminate, verify outcomes. [Pramaan](https://devpost.com/software/pramaan-ecqvtf)

## Positioning to use

> ContextRail is the evidence contract between enterprise agents. MCP moves verbs. ContextRail moves the case: the original request, the resolved subject, the citations, the active constraints, the approvals, the prior decisions, and the blockers — then it proves the resulting system state. A refusal is a successful governed result.

## Claims to avoid

- “The Freshworks MCP Gateway has 28 tools” as an official Freshworks number. Cite eesel, or drop the number.
- “Each gateway tool call is independent” as a Freshworks-specific insult. The protocol is independent; Freshworks still orchestrates inside Agent Studio.
- “Freshworks does not orchestrate workflows.”
- “No competitor carries shared context or supports approvals.”
- “100% safe” or “production ready” from a four-scenario fixture.

## Product implications

1. Lead the demo with one request and one forbidden action.
2. Make the capsule the protagonist. Show what survives each hop.
3. Treat refusal as success. Quote the clause.
4. Show the verify probe immediately after the connector call.
5. Present tools and skills as distribution, not as the plot.
6. Say the demo is fixture-backed. Judges punish fake production claims.

## Research limits

The event gallery is unpublished. Platform docs and the Devpost deadline can still move. Reconfirm the submit form the hour you upload.
