import { useEffect, useMemo, useRef, useState } from "react";
import "./Tutorial.css";

// v5: steps follow the Explore Cohort / Data Builder / Workflows layout.
const STORAGE_KEY = "cohort-studio.tutorial.v5";

export interface TutorialProgress {
  sourceChosen: boolean;
  dataLoaded: boolean;
  hasSources: boolean;
  joinPanelOpen: boolean;
  joinCreated: boolean;
  view: string;
  hasDataset: boolean;
  chatHistoryAvailable: boolean;
  assistantConfigured: boolean;
  /** False hides the assistant and Agent steps. */
  aiFeatures?: boolean;
}

type Step = {
  title: string; text: string; textNoAi?: string; ai?: true;
  target: (p: TutorialProgress) => string[];
  done: (p: TutorialProgress) => boolean;
  unavailable: (p: TutorialProgress) => boolean;
};
const ALL_STEPS: Step[] = [
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
    title: "Filter and style charts",
    text: "Click a bar or a slice to filter the cohort, or use Filters in the Data sources panel. Open Marks on a chart to draw it as a Bar, Column, Line, Area, Pie or Donut, and to set its color, size and value labels. Add chart adds another field.",
    target: () => [".chart-card .marks-menu > button", "[data-tutorial-target='add-chart']"],
    done: (p: TutorialProgress) => p.hasDataset,
    unavailable: (p: TutorialProgress) => !p.hasDataset,
  },
  {
    title: "Build a join in Data Builder",
    text: "Open Data Builder and drag tables onto the canvas, or press + beside a table. Click the badge between two tables to choose the join type and matching fields. In Fields, untick or rename fields, then Preview. Live opens the result in Explore Cohort; Extract saves every row as a database table you can refresh later.",
    target: (p: TutorialProgress) => p.view === "join"
      ? ["[aria-label='Join canvas']"] : ["[data-tutorial-target='nav-join']"],
    done: (p: TutorialProgress) => p.view === "join" || p.joinCreated,
    unavailable: (p: TutorialProgress) => !p.hasSources,
  },
  {
    title: "Export and save",
    text: "In Explore Cohort, Export downloads the rows (TSV, Parquet, JSON), a PDF of the charts, or saves the tab to Aurora. Save the open tabs as a view from the Data sources panel. Extract tabs show Refresh extract to rerun their join.",
    target: () => ["[aria-label='Export options']"],
    done: (p: TutorialProgress) => p.hasDataset,
    unavailable: (p: TutorialProgress) => !p.hasDataset,
  },
  {
    title: "Check assistant settings",
    ai: true,
    text: "Open Settings (the gear, top right) to choose a provider and model. Add a key if your provider needs one. If your workspace is already set up, continue.",
    target: () => ["[data-tutorial-target='nav-settings']"],
    done: (p: TutorialProgress) => p.assistantConfigured,
    unavailable: () => false,
  },
  {
    title: "Open an Agent conversation",
    ai: true,
    text: "Open Agent and select New chat. Ask it to build your cohort and inspect its tool results. Conversations are listed on the left; closing one keeps its history. Workflow plans require Run workflow approval.",
    target: (p: TutorialProgress) => p.view === "agent"
      ? ["[aria-label='Message the Studio Agent']"] : ["[data-tutorial-target='nav-agent']"],
    done: (p: TutorialProgress) => p.view === "agent",
    unavailable: () => false,
  },
  {
    title: "Review workflow runs",
    textNoAi: "Open Workflows to see each run's status, inputs, outputs and logs. Settings (the gear, top right) holds appearance, chart palette and notifications.",
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
      return { version: 3, step: Math.max(0, Math.min(ALL_STEPS.length - 1, saved.step)),
        dismissed: saved.dismissed === true };
    }
  } catch {}
  return { version: 3, step: 0, dismissed: false };
}

function saveProgress(progress: SavedProgress) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(progress)); } catch {}
}

/** `onOpen` lets the app show what the steps point at (the folded Data sources panel). */
export function Tutorial({ progress, onOpen }: { progress: TutorialProgress; onOpen?: () => void }) {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(() => readProgress().step);
  const [targetRect, setTargetRect] = useState<Rect | null>(null);
  const [targetAvailable, setTargetAvailable] = useState(false);
  const [targetRefresh, setTargetRefresh] = useState(0);
  const [panelPosition, setPanelPosition] = useState({ top: 24, right: 24 });
  const dialogRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const ai = progress.aiFeatures !== false;
  const steps = ai ? ALL_STEPS : ALL_STEPS.filter((s) => !s.ai);
  const current = steps[Math.min(step, steps.length - 1)];
  const done = current.done(progress);
  const unavailable = current.unavailable(progress) || !targetAvailable;
  const selectors = useMemo(() => current.target(progress), [step,
    progress.sourceChosen, progress.dataLoaded, progress.hasSources,
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
      // The overlay lives inside the zoomed #root (Display size), so convert
      // screen coordinates into the root's CSS pixels.
      const zoom = parseFloat(getComputedStyle(document.getElementById("root") ?? document.body).zoom) || 1;
      const screen = target.getBoundingClientRect();
      const rect = { top: screen.top / zoom, left: screen.left / zoom,
                     width: screen.width / zoom, height: screen.height / zoom };
      const viewWidth = window.innerWidth / zoom, viewHeight = window.innerHeight / zoom;
      const nextRect = { top: rect.top, left: rect.left,
        width: Math.max(24, rect.width), height: Math.max(24, rect.height) };
      setTargetRect((previous) => previous && Object.keys(nextRect).every((key) =>
        Math.abs(nextRect[key as keyof Rect] - previous[key as keyof Rect]) < 1)
        ? previous : nextRect);
      const panelScreen = dialogRef.current?.getBoundingClientRect();
      if (panelScreen) {
        const panel = { width: panelScreen.width / zoom, height: panelScreen.height / zoom };
        const right = rect.left < viewWidth / 2
          ? 16 : Math.max(16, viewWidth - panel.width - 16);
        const top = rect.top < viewHeight / 2
          ? Math.max(16, viewHeight - panel.height - 16) : 16;
        const left = viewWidth - right - panel.width;
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
      onOpen?.();
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
        <p id="tutorial-text">{!ai && current.textNoAi ? current.textNoAi : current.text}</p>
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
