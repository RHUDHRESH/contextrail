"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ChevronDown, Mic, MicOff, RefreshCw } from "lucide-react";

type SpeechResult = { isFinal: boolean; 0: { transcript: string } };
type SpeechEvent = { results: ArrayLike<SpeechResult> };
type SpeechError = { error: string };
type BrowserSpeechRecognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechEvent) => void) | null;
  onerror: ((event: SpeechError) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechWindow = Window & {
  SpeechRecognition?: new () => BrowserSpeechRecognition;
  webkitSpeechRecognition?: new () => BrowserSpeechRecognition;
};

type Persona = "employee" | "contractor" | "manager";
type Row = { action_id: string; label: string; verdict: string; state: string; clause: string; connector_mode: string; approver_id?: string | null; approver_name?: string | null; params_hash: string };
type Need = { role: "subject" | "peer" | "request"; mention: string | null; reason: string; candidates: { source_id: string; display_name: string; team?: string | null; role?: string | null }[] };
type RunView = { run_id: string; status: string; request_text: string; subject: string | null; peer: string | null; rows: Row[]; modes: Record<string, string>; needs: Need[] };
type Ticket = { status: "attempted" | "verified" | "unverified" | "unknown" | "blocked"; ticket_id?: number | null; mode: "LIVE" | "FIXTURE" };
type SavedRuns = Record<Persona, RunView[]>;
const defaultRuns: SavedRuns = { employee: [], contractor: [], manager: [] };
const personas: { id: Persona; title: string; name: string; role: string; description: string; suggestion: string }[] = [
  { id: "employee", title: "Employee", name: "Anil Kumar", role: "End person", description: "Ask for access or check your own request.", suggestion: "Give Anil the same access as Rahul Mehta" },
  { id: "contractor", title: "Contractor", name: "Priya Raghunathan", role: "Contractor", description: "See the request path with contractor identity and policy.", suggestion: "Priya starts Monday, give her everything she needs" },
  { id: "manager", title: "Manager", name: "Dana Osei", role: "Approver", description: "See pending work assigned to you and decide through the engine.", suggestion: "Give Anil the same access as Rahul Mehta" },
];
const scenarios: { title: string; persona: Persona; prompt: string; result: string }[] = [
  { title: "Match access", persona: "employee", prompt: "Give Anil the same access as Rahul Mehta", result: "Checks each permission" },
  { title: "Onboard Priya", persona: "contractor", prompt: "Priya starts Monday, give her everything she needs", result: "Uses her role and SOW" },
  { title: "Which Rahul?", persona: "employee", prompt: "Give Anil the same access as Rahul", result: "Asks you to choose" },
];

function title(status: string) {
  if (status === "done") return "Done";
  if (status === "awaiting_approval") return "Approval needed";
  if (status === "needs_input") return "More information needed";
  if (status === "partial") return "Partly done";
  return status.replaceAll("_", " ");
}

export default function EngineDemoPage() {
  const [persona, setPersona] = useState<Persona>("employee");
  const selected = useMemo(() => personas.find((item) => item.id === persona)!, [persona]);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [request, setRequest] = useState(personas[0].suggestion);
  const [run, setRun] = useState<RunView | null>(null);
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const requestRef = useRef<{ key: string; sourceRef: string } | null>(null);
  const [runs, setRuns] = useState<SavedRuns>(defaultRuns);
  const [pending, setPending] = useState<RunView[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [speechSupported, setSpeechSupported] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [speechError, setSpeechError] = useState("");
  const [speechLang, setSpeechLang] = useState("en-IN");
  const speechRef = useRef<BrowserSpeechRecognition | null>(null);

  useEffect(() => {
    const browser = window as SpeechWindow;
    const timer = window.setTimeout(() => setSpeechSupported(Boolean(browser.SpeechRecognition ?? browser.webkitSpeechRecognition)), 0);
    return () => { window.clearTimeout(timer); speechRef.current?.stop(); speechRef.current = null; };
  }, []);

  function toggleListening() {
    if (listening) { speechRef.current?.stop(); setListening(false); return; }
    const browser = window as SpeechWindow;
    const Recognition = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
    if (!Recognition) { setSpeechError("Speech input is unavailable in this browser. You can type your request below."); return; }
    const recognition = new Recognition();
    recognition.lang = speechLang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let transcript = "";
      for (const result of Array.from(event.results)) {
        transcript += `${result[0].transcript.trim()} `;
      }
      setRequest(transcript.trim());
    };
    recognition.onerror = (event) => {
      setSpeechError(event.error === "not-allowed" ? "Microphone permission was denied. Allow it in your browser or type your request." : `Speech input stopped: ${event.error}. You can type your request.`);
      setListening(false);
    };
    recognition.onend = () => { if (speechRef.current === recognition) { setListening(false); speechRef.current = null; } };
    speechRef.current = recognition;
    setSpeechError("");
    try { recognition.start(); setRequest(""); setListening(true); }
    catch { setSpeechError("Could not start the microphone. You can type your request."); setListening(false); speechRef.current = null; }
  }

  useEffect(() => {
    fetch("/api/engine-demo", { cache: "no-store" }).then((res) => res.json()).then((body) => setAvailable(body.available)).catch(() => setAvailable(false));
  }, []);

  const refreshPersona = useCallback(async (who: Persona) => {
    try {
      const response = await fetch(`/api/engine-demo?persona=${who}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Could not load this persona’s requests.");
      setRuns((previous) => {
        const next = { ...previous, [who]: body.runs ?? [] };
        try { window.localStorage.setItem("contextrail-engine-demo-runs-v1", JSON.stringify(next)); } catch { /* Engine remains the source of truth. */ }
        return next;
      });
      if (who === "manager") setPending(body.pending ?? []);
      setAvailable(body.available);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load this persona’s requests."); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refreshPersona(persona); }, 0);
    return () => window.clearTimeout(timer);
  }, [persona, refreshPersona]);

  function selectPersona(next: Persona) {
    speechRef.current?.stop(); setListening(false);
    setPersona(next); setError(""); setPending([]);
    setRequest(personas.find((item) => item.id === next)!.suggestion);
    setRun(null); setTicket(null); setError(""); setNotice("");
  }

  function chooseScenario(index: number) {
    speechRef.current?.stop(); setListening(false);
    const choice = scenarios[index];
    setPersona(choice.persona); setRequest(choice.prompt);
    setRun(null); setTicket(null); setError(""); setNotice("");
  }

  async function pickCandidate(role: "subject" | "peer", sourceId: string) {
    if (!run) return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/engine-demo", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ run_id: run.run_id, role, source_id: sourceId }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Could not resolve this person.");
      setRun(body as RunView);
      await refreshPersona(persona);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not resolve this person."); }
    finally { setBusy(false); }
  }

  async function selectHistory(item: RunView) {
    setRun(item); setTicket(null);
    try {
      const response = await fetch(`/api/engine-demo?run_id=${item.run_id}`, { cache: "no-store" });
      if (response.ok) setTicket(await response.json() as Ticket);
    } catch { /* The run remains available even if its ticket readback is unavailable. */ }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setNotice(""); setRun(null); setTicket(null);
    try {
      const key = `${persona}:${request.trim()}`;
      if (requestRef.current?.key !== key) requestRef.current = { key, sourceRef: crypto.randomUUID() };
      const response = await fetch("/api/engine-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona, request, source_ref: requestRef.current.sourceRef }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "The engine could not finish this request.");
      const view = body.run as RunView;
      setRun(view);
      setTicket(body.ticket as Ticket);
      setRuns((previous) => {
        const next = { ...previous, [persona]: [view, ...previous[persona].filter((item) => item.run_id !== view.run_id)].slice(0, 20) };
        try { window.localStorage.setItem("contextrail-engine-demo-runs-v1", JSON.stringify(next)); } catch { /* Run stays visible until this page closes. */ }
        return next;
      });
      setNotice(body.ticket?.status === "verified" ? `Freshservice ticket #${body.ticket.ticket_id} created and read back.` : "Request recorded by the Python engine. Freshservice ticket is not verified yet.");
      if (body.ticket?.status === "verified") requestRef.current = null;
      void refreshPersona(persona);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not run the request."); }
    finally { setBusy(false); }
  }

  async function decide(item: RunView, row: Row, decision: "approved" | "refused") {
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch("/api/engine-demo", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona: "manager", run_id: item.run_id, action_id: row.action_id, params_hash: row.params_hash, decision }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "The engine could not record that decision.");
      if (body.outcome === "rejected") throw new Error(body.reason ?? "The approval was rejected by engine policy.");
      setNotice(body.outcome === "already_decided" ? `Already decided by ${body.decided_by ?? "another approver"}.` : "Decision recorded by the engine.");
      await refreshPersona("manager");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not record decision."); }
    finally { setBusy(false); }
  }

  const history = runs[persona];
  const allApprovals = pending.flatMap((item) => item.rows.filter((row) => row.state === "awaiting" && row.approver_id === "p-dana").map((row) => ({ item, row })));

  return <div className="mx-auto max-w-[860px] px-5 pb-20 pt-10 md:px-8 md:pt-16">
    <p className="text-sm font-medium text-rail">Live demo</p>
    <h1 className="mt-2 font-display text-[36px] leading-tight text-text md:text-[48px]">One request, three views</h1>
    <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted">Ask for access or onboarding. See what was done, what needs approval, and the Freshservice ticket.</p>
    <details className="mt-4 text-sm text-muted"><summary className="cursor-pointer font-medium text-text">Northbeam Robotics · demo organization</summary><p className="mt-2 max-w-2xl leading-relaxed">Anil is a Payments employee; Rahul is a senior teammate. Priya is a Perception contractor starting Monday, with Marc as her manager and a statement of work limited to read-only perception SDK access. Dana is the Security approver. Their people, policies, and access records are fictional fixtures; Freshservice tickets are live. Onboarding here plans access only; it does not provision a laptop or email.</p></details>

    <section className="mt-7" aria-label="Choose a demo persona">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-dim">Choose who you are</p>
      <div className="grid gap-2 sm:grid-cols-3">{personas.map((item) => <button key={item.id} type="button" onClick={() => selectPersona(item.id)} aria-pressed={persona === item.id} className={`rounded-xl border p-3 text-left transition ${persona === item.id ? "border-rail bg-rail/5" : "border-line bg-panel hover:border-line-strong"}`}><span className="block text-sm font-semibold text-text">{item.title}</span><span className="mt-1 block text-sm text-text">{item.name}</span><span className="mt-1 block text-xs leading-relaxed text-muted">{item.description}</span></button>)}</div>
    </section>

    <div className="mt-5 flex items-center justify-between rounded-xl border border-line bg-panel px-4 py-3"><div><span className="text-xs text-dim">Current persona</span><p className="mt-0.5 text-sm font-medium text-text">{selected.name} <span className="font-normal text-muted">· {selected.role}</span></p></div><span className="text-xs text-muted">{available === null ? "Checking engine…" : available ? "Engine ready" : "Engine offline"}</span></div>

    <form id="engine-request" onSubmit={submit} className="mt-5 rounded-[18px] border border-line-strong bg-panel p-4 shadow-[0_12px_40px_rgba(70,53,36,.06)] md:p-5">
      <label htmlFor="request-text" className="mb-2 block text-sm font-medium text-text">{persona === "manager" ? "Create a request as Dana" : `What does ${selected.name} need?`}</label>
      <textarea id="request-text" value={request} onChange={(event) => setRequest(event.target.value)} rows={3} className="w-full resize-y rounded-lg border border-line bg-transparent p-3 text-[16px] leading-6 text-text outline-none focus:border-rail" />
      <div className="mt-2 flex flex-wrap items-center gap-3"><button type="button" onClick={toggleListening} disabled={speechSupported !== true || busy} aria-label={listening ? "Stop listening" : "Speak your request"} aria-pressed={listening} className="inline-flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-text disabled:cursor-not-allowed disabled:opacity-40">{listening ? <MicOff className="size-4" /> : <Mic className="size-4" />}{listening ? "Stop listening" : "Speak"}</button><label className="sr-only" htmlFor="speech-language">Speech language</label><select id="speech-language" value={speechLang} onChange={(event) => setSpeechLang(event.target.value)} disabled={listening || speechSupported !== true} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm text-text disabled:opacity-40"><option value="en-IN">English</option><option value="hi-IN">हिन्दी</option><option value="ta-IN">தமிழ்</option></select><span role="status" className="text-xs text-muted">{listening ? "Listening… Speak your request, then submit it." : speechSupported === false ? "Speech input is unavailable in this browser." : "Review the transcript before submitting."}</span></div>
      {speechError && <p role="alert" className="mt-2 text-xs text-stop">{speechError}</p>}
      <div className="mt-3 flex flex-wrap gap-2" aria-label="Try a scenario">{scenarios.map((scenario, index) => <button key={scenario.title} type="button" onClick={() => chooseScenario(index)} className="rounded-full border border-line px-3 py-1.5 text-left text-xs text-text hover:border-line-strong"><span className="font-medium">{scenario.title}</span><span className="ml-1 text-dim">· {scenario.result}</span></button>)}</div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4"><span className="text-xs text-muted">Identity is mapped server-side to a fixed fixture account.</span><button type="submit" disabled={!available || busy || listening || request.trim().length < 8} className="inline-flex h-10 items-center gap-2 rounded-lg bg-rail px-5 text-sm font-semibold text-panel disabled:cursor-not-allowed disabled:opacity-40">{busy ? "Working…" : "Run request"}<ArrowRight className="size-4" /></button></div>
    </form>
    {!available && available !== null && <p role="status" className="mt-3 text-sm text-muted">Start the local pilot engine to use this demo.</p>}
    {error && <p role="alert" className="mt-3 rounded-xl border border-stop/40 bg-stop/5 p-3 text-sm text-text">{error}</p>}
    {notice && <p role="status" className="mt-3 rounded-xl border border-line bg-panel p-3 text-sm text-text">{notice}</p>}

    {run && <RunCard run={run} ticket={ticket} heading="Latest request" busy={busy} onPick={pickCandidate} />}

    {persona === "manager" ? <section id="engine-history" className="mt-8" aria-label="Manager approval queue"><div className="flex items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-dim">Dana’s approvals</p><h2 className="mt-1 font-display text-2xl text-text">Other side of the request</h2></div><button type="button" onClick={() => void refreshPersona("manager")} disabled={busy} className="inline-flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm text-text"><RefreshCw className="size-4" /> Refresh</button></div>
      {allApprovals.length === 0 ? <div className="mt-3 rounded-xl border border-dashed border-line-strong px-5 py-8 text-center text-sm text-muted">No requests are waiting for Dana. Submit a request as Anil, then switch back to Manager.</div> : <div className="mt-3 space-y-3">{allApprovals.map(({ item, row }) => <div key={`${item.run_id}:${row.action_id}`} className="rounded-xl border border-line-strong bg-panel p-4"><p className="text-xs text-dim">Request {item.run_id.slice(0, 8)} · For {item.subject ?? "employee"}{item.peer ? ` · Based on ${item.peer}` : ""}</p><h3 className="mt-1 font-medium text-text">{row.label}</h3><p className="mt-2 text-sm leading-relaxed text-muted">{item.request_text}</p><p className="mt-2 text-xs text-muted">{row.verdict} · {row.clause}</p><div className="mt-4 flex gap-2"><button type="button" disabled={busy} onClick={() => void decide(item, row, "approved")} className="h-9 rounded-lg bg-rail px-4 text-sm font-semibold text-panel disabled:opacity-50">Approve</button><button type="button" disabled={busy} onClick={() => void decide(item, row, "refused")} className="h-9 rounded-lg border border-line px-4 text-sm font-medium text-text disabled:opacity-50">Decline</button></div></div>)}</div>}
    </section> : <section id="engine-history" className="mt-8" aria-label="My requests"><p className="text-xs font-semibold uppercase tracking-wide text-dim">{selected.name} · this browser</p><h2 className="mt-1 font-display text-2xl text-text">My requests</h2>{history.length === 0 ? <p className="mt-3 rounded-xl border border-dashed border-line-strong px-5 py-7 text-center text-sm text-muted">No requests yet for this persona.</p> : <div className="mt-3 space-y-2">{history.map((item) => <button key={item.run_id} type="button" onClick={() => void selectHistory(item)} className="w-full rounded-xl border border-line bg-panel p-4 text-left hover:border-line-strong"><span className="block text-sm font-medium text-text">{item.request_text}</span><span className="mt-1 block text-xs text-muted">{title(item.status)} · {item.rows.length} actions · {item.run_id.slice(0, 8)}</span></button>)}</div>}</section>}

    <p className="mt-7 text-xs leading-relaxed text-dim">Requests use the live engine and create Freshservice tickets when verified. Personas and access systems are sample fixtures, not authenticated accounts or real access grants. Browser decisions use the engine’s demo channel; Slack approval is a separate integration.</p>
  </div>;
}

function RunCard({ run, ticket, heading, busy, onPick }: { run: RunView; ticket?: Ticket | null; heading: string; busy: boolean; onPick: (role: "subject" | "peer", sourceId: string) => Promise<void> }) {
  const verified = run.rows.filter((row) => row.state === "verified").length;
  const waiting = run.rows.filter((row) => row.state === "awaiting").length;
  const refused = run.rows.filter((row) => row.verdict === "REFUSE").length;
  return <section className="mt-5 rounded-2xl border border-line-strong bg-panel p-5" aria-label={heading}>
    <p className="text-xs font-medium text-rail">{heading} · Run {run.run_id.slice(0, 8)}</p>
    <h2 className="mt-1 font-display text-2xl text-text">{title(run.status)}</h2>
    <p className="mt-1 text-sm text-muted">{run.subject ? `For ${run.subject}` : run.needs?.some((need) => need.role === "peer") ? "Reference person needs clarification" : "Person needs clarification"}{run.peer ? `, based on ${run.peer}` : ""}.</p>
    {run.rows.length > 0 && <p className="mt-2 text-sm text-text">{verified} verified · {waiting} need approval · {refused} refused</p>}
    {ticket && <p className="mt-2 text-sm text-text">Freshservice: {ticket.status === "verified" && ticket.ticket_id ? <a className="font-medium text-rail underline" target="_blank" rel="noreferrer" href={`https://freshworks065.freshservice.com/a/tickets/${ticket.ticket_id}`}>Ticket #{ticket.ticket_id} · {ticket.mode}</a> : `${ticket.status} · ${ticket.mode}`}</p>}
    {run.needs?.map((need, index) => <div key={`${need.role}:${index}`} className="mt-4 rounded-xl border border-line bg-panel-2 p-4">
      <p className="text-sm font-medium text-text">{need.reason === "ambiguous" ? `Which ${need.mention ?? "person"} did you mean?` : need.reason === "no_mention" ? "Who is this request for?" : "Please clarify this request."}</p>
      {need.candidates?.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{need.candidates.map((candidate) => <button key={candidate.source_id} type="button" disabled={busy || need.role === "request"} onClick={() => void onPick(need.role as "subject" | "peer", candidate.source_id)} className="rounded-lg border border-line-strong bg-panel px-3 py-2 text-left text-sm text-text disabled:opacity-50"><span className="font-medium">{candidate.display_name}</span><span className="ml-1 text-xs text-muted">· {candidate.team ?? candidate.role ?? candidate.source_id}</span></button>)}</div>}
    </div>)}
    {run.rows.length > 0 && <details className="mt-4 border-t border-line pt-3"><summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-text">View {run.rows.length} steps <ChevronDown className="size-4" /></summary><div className="mt-3 space-y-2">{run.rows.map((row) => <div key={row.action_id} className="rounded-xl bg-panel-2 px-3 py-3 text-sm"><div className="flex items-start justify-between gap-3"><span className="font-medium text-text">{row.label}</span><span className="shrink-0 text-xs text-muted">{row.verdict} · {row.state}</span></div><p className="mt-1 text-xs leading-relaxed text-muted">{row.clause}{row.approver_name ? ` · Approver: ${row.approver_name}` : ""}</p></div>)}</div></details>}
    <details className="mt-4 border-t border-line pt-3"><summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-text">Connector details <ChevronDown className="size-4" /></summary><p className="mt-2 text-xs text-muted">{Object.entries(run.modes).map(([name, mode]) => `${name}: ${mode}`).join(" · ")}</p></details>
  </section>;
}
