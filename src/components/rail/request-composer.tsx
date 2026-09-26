"use client";

import { useState } from "react";
import { Check, ChevronDown, Phone, Plus, X } from "lucide-react";
import { getScenario } from "@/lib/contextrail/scenarios";
import { resolveIntent } from "@/lib/contextrail/intent";
import { RunConsole } from "./run-console";

type Launch = { request: string; requesterId?: string; scenarioId?: string | null };
const PEOPLE = ["Priya Raghunathan", "Marc Liu", "Alicia Fenn", "Priyanka Rao", "Dana Osei"];
const WORKFLOWS = [
  { id: "contractor", name: "Onboard someone", example: "Get Priya ready for her first day." },
  { id: "access", name: "Request access", example: "Give Priya access to fleet-api." },
  { id: "refund", name: "Resolve a customer issue", example: "Review Meridian Freight's outage credit." },
];

export function RequestComposer({ preset }: { preset?: string | null }) {
  const seeded = getScenario(preset);
  const [request, setRequest] = useState(seeded?.request ?? "");
  const [people, setPeople] = useState<string[]>([]);
  const [personInput, setPersonInput] = useState("");
  const [workflow, setWorkflow] = useState(seeded ? WORKFLOWS.find((item) => item.id === seeded.id)?.name ?? "" : "");
  const [workflowInput, setWorkflowInput] = useState("");
  const [callRequested, setCallRequested] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [launch, setLaunch] = useState<Launch | null>(null);
  const [unsupported, setUnsupported] = useState(false);
  if (launch) return <RunConsole autoStart={launch} />;

  function addPerson(value: string) {
    const name = value.trim();
    if (!name || people.some((person) => person.toLowerCase() === name.toLowerCase())) return;
    setPeople((current) => [...current, name]);
    setPersonInput("");
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const words = request.trim();
    if (words.length < 8) return;
    const knownWorkflow = !workflow || WORKFLOWS.some((item) => item.name === workflow);
    const sampleSubject = /\b(priya|meridian)\b/i.test(words);
    const recognizedIntent = resolveIntent([words, workflow].join(" ")).matchedSignals.length > 0;
    if (!knownWorkflow || !sampleSubject || !recognizedIntent) {
      setUnsupported(true);
      return;
    }
    const context = [
      people.length ? `People involved: ${people.join(", ")}.` : "",
      workflow ? `Workflow: ${workflow}.` : "",
      callRequested ? "Contact preference: Please call me about this request." : "",
    ].filter(Boolean);
    setLaunch({
      request: [words, ...context].join("\n"),
      requesterId: seeded?.requesterId ?? (workflow === "Resolve a customer issue" ? "U-3310" : "U-2201"),
      scenarioId: WORKFLOWS.find((item) => item.name === workflow)?.id ?? null,
    });
  }

  return (
    <div className="mx-auto w-full max-w-[760px] px-5 pb-14 pt-12 md:px-8 md:pt-24">
      <div className="mb-9">
        <p className="text-sm font-medium text-rail">Your workspace</p>
        <h1 className="mt-3 font-display text-[40px] font-normal leading-[1.13] tracking-tight text-text md:text-[54px]">What needs to happen?</h1>
        <p className="mt-4 max-w-xl text-[16px] leading-relaxed text-muted">Tell us what you need. Add people or a workflow if you like.</p>
      </div>
      <form onSubmit={submit} className="rounded-[20px] border border-line-strong bg-panel p-4 shadow-[0_12px_40px_rgba(70,53,36,.07)] md:p-5">
        <label htmlFor="request" className="sr-only">Describe your request</label>
        <textarea id="request" value={request} onChange={(event) => { setRequest(event.target.value); setUnsupported(false); }} placeholder="For example, get Priya ready to join engineering on Monday…" rows={4} className="w-full resize-y bg-transparent text-[17px] leading-7 text-text outline-none placeholder:text-muted/80" />
        {(people.length > 0 || workflow || callRequested) && (
          <div className="mb-4 flex flex-wrap gap-2" aria-label="Added request context">
            {people.map((person) => <span key={person} className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-panel-2 px-3 py-1.5 text-xs text-text">{person}<button type="button" onClick={() => setPeople((current) => current.filter((item) => item !== person))} aria-label={`Remove ${person}`} className="text-muted hover:text-text"><X className="size-3" /></button></span>)}
            {workflow && <span className="inline-flex items-center gap-1.5 rounded-full border border-rail/40 bg-rail/10 px-3 py-1.5 text-xs text-text">{workflow}<button type="button" onClick={() => setWorkflow("")} aria-label="Remove workflow" className="text-muted hover:text-text"><X className="size-3" /></button></span>}
            {callRequested && <span className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-panel-2 px-3 py-1.5 text-xs text-text"><Phone className="size-3" /> Ask for a call<button type="button" onClick={() => setCallRequested(false)} aria-label="Remove call preference" className="text-muted hover:text-text"><X className="size-3" /></button></span>}
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <button type="button" onClick={() => setAddOpen((open) => !open)} aria-expanded={addOpen} className="inline-flex h-10 items-center gap-2 rounded-lg border border-line-strong px-3 text-sm font-medium text-text hover:bg-panel-2"><Plus className="size-4" /> Add <ChevronDown className="size-4 text-muted" /></button>
          <button type="submit" disabled={request.trim().length < 8} className="inline-flex h-10 items-center justify-center rounded-lg bg-rail px-5 text-sm font-semibold text-ink hover:bg-rail/90 disabled:cursor-not-allowed disabled:opacity-40">Send request</button>
        </div>
        {addOpen && <div className="mt-4 grid gap-5 rounded-xl border border-line-strong bg-panel-2 p-4 md:grid-cols-2">
          <div>
            <label htmlFor="person-input" className="text-sm font-semibold text-text">People</label>
            <p className="mt-1 text-xs text-muted">Mention anyone involved.</p>
            <div className="mt-3 flex gap-2"><input id="person-input" value={personInput} onChange={(event) => setPersonInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addPerson(personInput); } }} placeholder="Name" className="h-10 min-w-0 flex-1 rounded-lg border border-line-strong bg-panel px-3 text-sm text-text placeholder:text-dim" /><button type="button" onClick={() => addPerson(personInput)} aria-label="Add person" className="grid size-10 place-items-center rounded-lg border border-line-strong text-text hover:bg-panel-3"><Plus className="size-4" /></button></div>
            <div className="mt-2 flex flex-wrap gap-1.5">{PEOPLE.filter((person) => !people.includes(person) && (!personInput || person.toLowerCase().includes(personInput.toLowerCase()))).slice(0, 3).map((person) => <button key={person} type="button" onClick={() => addPerson(person)} className="rounded-full border border-line-strong px-2.5 py-1 text-xs text-muted hover:border-rail hover:text-text">+ {person}</button>)}</div>
          </div>
          <div>
            <label htmlFor="workflow-input" className="text-sm font-semibold text-text">Workflow</label>
            <p className="mt-1 text-xs text-muted">Name the kind of help you need.</p>
            <div className="mt-3 flex gap-2"><input id="workflow-input" value={workflowInput} onChange={(event) => setWorkflowInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); if (workflowInput.trim()) { setWorkflow(workflowInput.trim()); setWorkflowInput(""); } } }} placeholder="Workflow name" className="h-10 min-w-0 flex-1 rounded-lg border border-line-strong bg-panel px-3 text-sm text-text placeholder:text-dim" /><button type="button" onClick={() => { if (workflowInput.trim()) { setWorkflow(workflowInput.trim()); setWorkflowInput(""); } }} aria-label="Add workflow" className="grid size-10 place-items-center rounded-lg border border-line-strong text-text hover:bg-panel-3"><Plus className="size-4" /></button></div>
            <div className="mt-2 space-y-1">{WORKFLOWS.filter((item) => !workflowInput || item.name.toLowerCase().includes(workflowInput.toLowerCase())).map((item) => <button key={item.id} type="button" onClick={() => { setWorkflow(item.name); if (!request.trim()) setRequest(item.example); }} aria-pressed={workflow === item.name} className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm text-text hover:bg-panel-3">{item.name}{workflow === item.name && <Check className="size-4 text-rail" />}</button>)}</div>
            <label className="mt-3 flex cursor-pointer items-center gap-2 border-t border-line pt-3 text-sm text-text"><input type="checkbox" checked={callRequested} onChange={(event) => setCallRequested(event.target.checked)} className="size-4 accent-rail" /><Phone className="size-4 text-muted" /> Ask someone to call me</label>
            {callRequested && <p className="mt-1 pl-6 text-xs text-muted">Recorded as a preference in this demo. No call is placed.</p>}
          </div>
        </div>}
      </form>
      {unsupported && <div role="status" className="mt-4 rounded-xl border border-caution/35 bg-caution/5 px-4 py-3 text-sm leading-relaxed text-text">This demo only has sample records for Priya and Meridian Freight, and three prepared workflows. Your request was not sent or acted on. Try a sample person and workflow to see the flow.</div>}
      <p className="mt-4 text-xs leading-relaxed text-dim">Preview with sample data · No live ticket or call is placed.</p>
    </div>
  );
}
