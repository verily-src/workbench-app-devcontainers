import { useEffect, useMemo, useRef, useState } from "react";
import "./Tutorial.css";

const STORAGE_KEY = "cohort-studio.tutorial.v3";

export interface TutorialProgress {
  sourceChosen: boolean;
  dataLoaded: boolean;
  hasSources: boolean;
  omopAvailable: boolean;
  omopActive: boolean;
  omopOpenedCount: number;
  joinPanelOpen: boolean;
  joinCreated: boolean;
  view: string;
  hasDataset: boolean;
  chatHistoryAvailable: boolean;
  assistantConfigured: boolean;
}

const steps = [
  {
    title: "Choose a source",
    text: "Choose a source type, then select its datasource. The table picker appears after the datasource loads.",
    target: () => {
      const type = document.querySelector<HTMLSelectElement>("[aria-label='Source type']");
      return [type?.value ? "[aria-label='Datasource']" : "[aria-label='Source type']"];
    },
    done: (p: TutorialProgress) => p.sourceChosen,
    unavailable: (p: TutorialProgress) => !p.hasSources,
  },
  {
    title: "Open a table",
    text: "For Aurora, choose Schema → Table → Load table. For S3, choose File folder → File → Load file. You can rename the opened tab.",
    target: () => ["[aria-label='Table']", "[aria-label='File']", "[aria-label='Schema']"],
    done: (p: TutorialProgress) => p.dataLoaded,
    unavailable: (p: TutorialProgress) => !p.sourceChosen,
  },
  {
    title: "Build an OMOP cohort",
    text: "Select OMOP beside Tables. Choose concepts and demographic filters to update the cohort summary. Use Charts or Table to inspect it, then View people to open the cohort.",
    target: (p: TutorialProgress) => p.omopActive
      ? ["[aria-label='OMOP cohort builder']"] : ["[data-tutorial-target='omop-toggle']"],
    done: (p: TutorialProgress) => p.omopOpenedCount > 0,
    unavailable: (p: TutorialProgress) => !p.omopAvailable,
  },
  {
    title: "Open related tables",
    text: "In OMOP, use Explore clinical tables. Keep Restrict to current cohort selected to open events for your cohort. For genetics, return to Tables and choose the genetics schema.",
    target: () => ["[aria-label='OMOP cohort builder']"],
    done: (p: TutorialProgress) => p.omopOpenedCount > 1,
    unavailable: (p: TutorialProgress) => !p.omopAvailable || p.omopOpenedCount === 0,
  },
  {
    title: "Join on matching keys",
    text: "Open Join and add an Aurora table or S3 file. Match person_id to samples.person_id, then sample_id to genotypes.sample_id. Preview the result and Generated SQL. Cross-source joins use DuckDB and require your consent.",
    target: (p: TutorialProgress) => p.joinPanelOpen
      ? ["[aria-label='Join type']"] : ["[data-tutorial-target='join-button']"],
    done: (p: TutorialProgress) => p.joinCreated,
    unavailable: (p: TutorialProgress) => !p.hasSources,
  },
  {
    title: "Check assistant settings",
    text: "Open Settings to choose a provider and model. Add a key if your provider needs one. If your workspace is already set up, continue.",
    target: () => ["[data-tutorial-target='nav-settings']"],
    done: (p: TutorialProgress) => p.assistantConfigured,
    unavailable: () => false,
  },
  {
    title: "Open an Agent conversation",
    text: "Open Agent and select New chat. Ask it to build your cohort and inspect its tool results. Conversations are listed on the left; closing one keeps its history. Workflow plans require Run workflow approval.",
    target: (p: TutorialProgress) => p.view === "agent"
      ? ["[aria-label='Message the Studio Agent']"] : ["[data-tutorial-target='nav-agent']"],
    done: (p: TutorialProgress) => p.view === "agent",
    unavailable: () => false,
  },
  {
    title: "Review workflow runs",
    text: "Open Workflows to inspect actual run status. For the demo, ask Agent to prepare cohort-genetics-demo with nextflow_params input and nextflow_outputs output. Review the mapping before Run workflow. After completion, ask Agent to verify the output files and open the summary dashboard.",
    target: () => ["[data-tutorial-target='nav-workflows']"],
    done: (p: TutorialProgress) => p.view === "workflows",
    unavailable: () => false,
  },
];

type SavedProgress = { version: 3; step: number; dismissed: boolean };
type Rect = { top: number; left: number; width: number; height: number };

function readProgress(): SavedProgress {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (saved?.version === 3 && Number.isInteger(saved.step)) {
      return { version: 3, step: Math.max(0, Math.min(steps.length - 1, saved.step)),
        dismissed: saved.dismissed === true };
    }
  } catch {}
  return { version: 3, step: 0, dismissed: false };
}

function saveProgress(progress: SavedProgress) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(progress)); } catch {}
}

export function Tutorial({ progress }: { progress: TutorialProgress }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(() => readProgress().step);
  const [targetRect, setTargetRect] = useState<Rect | null>(null);
  const [targetAvailable, setTargetAvailable] = useState(false);
  const [targetRefresh, setTargetRefresh] = useState(0);
  const [panelPosition, setPanelPosition] = useState({ top: 24, right: 24 });
  const dialogRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const current = steps[step];
  const done = current.done(progress);
  const unavailable = current.unavailable(progress) || !targetAvailable;
  const selectors = useMemo(() => current.target(progress), [step,
    progress.sourceChosen, progress.dataLoaded, progress.hasSources,
    progress.omopAvailable, progress.omopActive, progress.omopOpenedCount,
    progress.joinPanelOpen, progress.joinCreated, progress.view,
    progress.hasDataset, progress.chatHistoryAvailable, progress.assistantConfigured,
    targetRefresh]);
  const keyboardState = useRef({ step, done });
  const changeStepRef = useRef<(next: number) => void>(() => undefined);
  keyboardState.current = { step, done };

  const close = () => setOpen(false);
  const dismiss = () => {
    saveProgress({ version: 3, step: 0, dismissed: true });
    setStep(0);
    close();
  };

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close(); return; }
      if (!event.altKey) return;
      if (document.activeElement instanceof HTMLElement
          && ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
      if (event.key === "ArrowRight" && keyboardState.current.done) {
        event.preventDefault(); changeStepRef.current(keyboardState.current.step + 1);
      }
      if (event.key === "ArrowLeft" && keyboardState.current.step > 0) {
        event.preventDefault(); changeStepRef.current(keyboardState.current.step - 1);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const onChange = () => setTargetRefresh((previous) => previous + 1);
    document.addEventListener("change", onChange, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("change", onChange, true);
      returnFocusRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const findTarget = () => selectors.map((selector) =>
      document.querySelector<HTMLElement>(selector)).find((element) =>
      element && element.getClientRects().length > 0
      && getComputedStyle(element).visibility !== "hidden") ?? null;
    let target = findTarget();
    if (target) target.scrollIntoView({ block: "nearest", inline: "nearest" });
    const update = () => {
      target = findTarget();
      setTargetAvailable(Boolean(target));
      if (!target) { setTargetRect(null); return; }
      const rect = target.getBoundingClientRect();
      const nextRect = { top: rect.top, left: rect.left,
        width: Math.max(24, rect.width), height: Math.max(24, rect.height) };
      setTargetRect((previous) => previous && Object.keys(nextRect).every((key) =>
        Math.abs(nextRect[key as keyof Rect] - previous[key as keyof Rect]) < 1)
        ? previous : nextRect);
      const panel = dialogRef.current?.getBoundingClientRect();
      if (panel) {
        const right = rect.left < window.innerWidth / 2
          ? 16 : Math.max(16, window.innerWidth - panel.width - 16);
        const top = rect.top < window.innerHeight / 2
          ? Math.max(16, window.innerHeight - panel.height - 16) : 16;
        const left = window.innerWidth - right - panel.width;
        setPanelPosition((previous) => previous.top === top && previous.right === left
          ? previous : { top, right: left });
      }
    };
    const frame = requestAnimationFrame(update);
    const observer = new ResizeObserver(update);
    if (target) observer.observe(target);
    window.addEventListener("resize", update);
    document.addEventListener("scroll", update, true);
    const mutations = new MutationObserver(update);
    mutations.observe(document.body, { childList: true, subtree: true });
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      mutations.disconnect();
      window.removeEventListener("resize", update);
      document.removeEventListener("scroll", update, true);
    };
  }, [open, step, selectors]);

  const changeStep = (next: number) => {
    const bounded = Math.max(0, Math.min(steps.length - 1, next));
    setStep(bounded);
    saveProgress({ version: 3, step: bounded, dismissed: false });
  };
  changeStepRef.current = changeStep;

  return <>
    <button className="tutorial-trigger" type="button" onClick={() => {
      const saved = readProgress();
      setStep(saved.dismissed ? 0 : saved.step);
      setOpen(true);
    }}>Tutorial</button>
    {open && <>
      {targetRect && <div className="tutorial-spotlight" data-target={selectors[0]}
        aria-hidden="true" style={{
        top: targetRect.top - 5, left: targetRect.left - 5,
        width: targetRect.width + 10, height: targetRect.height + 10,
      }} />}
      <section className="tutorial-dialog" role="dialog" aria-modal="false"
        aria-labelledby="tutorial-title" aria-describedby="tutorial-text"
        ref={dialogRef} style={{ top: panelPosition.top, left: panelPosition.right }}>
        <div className="tutorial-heading">
          <p className="tutorial-count">Step {step + 1} of {steps.length}</p>
          <button className="tutorial-close" type="button"
            aria-label="Close tutorial" onClick={close}>×</button>
        </div>
        <h2 id="tutorial-title">{current.title}</h2>
        <p id="tutorial-text">{current.text}</p>
        {unavailable && <p className="tutorial-unavailable" role="status">
          This step is not available for the current sources or tab. Skip it to continue.
        </p>}
        {done && <p className="tutorial-complete" role="status">Done</p>}
        <div className="tutorial-progress" aria-label={`Step ${step + 1} of ${steps.length}`}>
          {steps.map((item, index) => <span key={item.title}
            className={index === step ? "current" : index < step ? "done" : ""} />)}
        </div>
        <div className="tutorial-actions">
          <button className="quiet" type="button" onClick={dismiss}>Skip tutorial</button>
          <div>
            {step > 0 && <button className="quiet" type="button"
              onClick={() => changeStep(step - 1)}>Back</button>}
            {!done && step < steps.length - 1 && <button className="quiet" type="button"
              onClick={() => changeStep(step + 1)}>Skip step</button>}
            {step < steps.length - 1 ? <button className="quiet" type="button"
              disabled={!done} onClick={() => changeStep(step + 1)}>
              Next
            </button> : <button type="button" onClick={dismiss} disabled={!done}>Finish</button>}
          </div>
        </div>
        <p className="tutorial-shortcuts">Use Alt+←/→ to move between steps. Esc closes.</p>
      </section>
    </>}
  </>;
}
