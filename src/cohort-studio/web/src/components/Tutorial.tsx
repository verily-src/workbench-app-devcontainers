import { useEffect, useRef, useState } from "react";
import "./Tutorial.css";

const STORAGE_KEY = "cohort-studio.tutorial.v1";

const steps = [
  {
    title: "Choose data",
    text: "Choose an available source and table, then open it in Explore. You can also upload a CSV file. Start with the source that contains the people or records you need.",
  },
  {
    title: "Build an OMOP cohort",
    text: "Open OMOP Builder, search for a concept, and add it to a rule. Set the criteria, then build the cohort. Review the count and attrition before you explore the result.",
  },
  {
    title: "Open tables",
    text: "Open a cohort result table to inspect its people or events. In Explore, each opened table has its own tab, so you can move between related tables.",
  },
  {
    title: "Join on the right keys",
    text: "Load both datasets and open Join. Choose a base table, add the other table, then select columns that identify the same entity at the same level. Review the preview and row count before you run the join.",
  },
  {
    title: "Set up the assistant",
    text: "In Settings, choose an available provider and model, then add a key if that provider needs one. Open the assistant from a dataset or cohort to ask a question. Reopen its chat to restore your saved history.",
  },
];

type SavedProgress = { version: 1; step: number; dismissed: boolean };

function readProgress(): SavedProgress {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (saved?.version === 1 && Number.isInteger(saved.step)) {
      return { version: 1, step: Math.max(0, Math.min(steps.length - 1, saved.step)),
        dismissed: saved.dismissed === true };
    }
  } catch {}
  return { version: 1, step: 0, dismissed: false };
}

function saveProgress(progress: SavedProgress) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(progress)); }
  catch {}
}

export function Tutorial() {
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(() => readProgress().step);
  const dialogRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const close = () => setOpen(false);
  const dismiss = () => {
    const progress = { version: 1 as const, step: 0, dismissed: true };
    setStep(0);
    saveProgress(progress);
    close();
  };

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement : null;
    const dialog = dialogRef.current;
    const initial = dialog?.querySelector<HTMLElement>("[data-tutorial-initial]");
    initial?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled])'));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [open]);

  const changeStep = (next: number) => {
    const bounded = Math.max(0, Math.min(steps.length - 1, next));
    setStep(bounded);
    saveProgress({ version: 1, step: bounded, dismissed: false });
  };

  return (
    <>
      <button className="tutorial-trigger" type="button" onClick={() => {
        const progress = readProgress();
        setStep(progress.dismissed ? 0 : progress.step);
        setOpen(true);
      }}>Tutorial</button>
      {open && <div className="tutorial-overlay">
        <div className="tutorial-dialog" role="dialog" aria-modal="true"
          aria-labelledby="tutorial-title" aria-describedby="tutorial-text"
          ref={dialogRef}>
          <div className="tutorial-heading">
            <p className="tutorial-count">Step {step + 1} of {steps.length}</p>
            <button className="tutorial-close" type="button"
              aria-label="Close tutorial" data-tutorial-initial onClick={close}>×</button>
          </div>
          <h2 id="tutorial-title">{steps[step].title}</h2>
          <p id="tutorial-text">{steps[step].text}</p>
          <div className="tutorial-progress" aria-label={`Step ${step + 1} of ${steps.length}`}>
            {steps.map((item, index) => <span key={item.title}
              className={index === step ? "current" : index < step ? "done" : ""} />)}
          </div>
          <div className="tutorial-actions">
            <button className="quiet" type="button" onClick={dismiss}>Skip tutorial</button>
            <div>
              {step > 0 && <button className="quiet" type="button"
                onClick={() => changeStep(step - 1)}>Back</button>}
              {step < steps.length - 1
                ? <button type="button" onClick={() => changeStep(step + 1)}>Next</button>
                : <button type="button" onClick={dismiss}>Finish</button>}
            </div>
          </div>
        </div>
      </div>}
    </>
  );
}
