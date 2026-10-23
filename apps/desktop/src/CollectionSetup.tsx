import { useEffect, useRef, useState, type ReactElement } from "react";
import type { RegisteredCollection } from "./CollectionSettings";
import { displayLocalPath } from "./collectionSource";

export function needsCollectionSetup(collection: RegisteredCollection): boolean {
  return !collection.archived && collection.mediaModes.includes("referenced-local")
    && (Boolean(collection.setupPending) || !collection.mediaRoot);
}

interface Props {
  collection: RegisteredCollection;
  openAfter: boolean;
  initialStep?: "intro" | "folder";
  onChooseFolder: () => Promise<RegisteredCollection | null>;
  onFinish: () => Promise<void>;
  onCancel: () => void;
}

export function CollectionSetup({ collection, openAfter, initialStep = "intro", onChooseFolder, onFinish, onCancel }: Props): ReactElement {
  const [step, setStep] = useState<"intro" | "folder" | "review">(initialStep);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const locked = useRef(false);
  const dialog = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const onboarding = collection.onboarding;
  const missing = Math.max(0, collection.mediaExpected - collection.mediaFound);
  const canContinue = Boolean(collection.mediaRoot) && collection.mediaFound > 0;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    heading.current?.focus();
    return () => previous?.focus();
  }, []);
  useEffect(() => { heading.current?.focus(); }, [step]);

  async function chooseFolder(): Promise<void> {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(null); setNotice(null);
    try {
      const result = await onChooseFolder();
      if (result) setStep("review");
      else setNotice("No folder selected. Choose a folder when you’re ready, or finish setup later.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { locked.current = false; setBusy(false); }
  }

  async function finish(): Promise<void> {
    if (locked.current || !canContinue) return;
    locked.current = true; setBusy(true); setError(null);
    try { await onFinish(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { locked.current = false; setBusy(false); }
  }

  const title = step === "intro" ? `Set up ${collection.title}`
    : step === "folder" ? onboarding?.media_folder_prompt ?? `Where are the videos for ${collection.title}?`
    : "Review your video folder";

  return (
    <div className="settings-backdrop collection-setup-overlay">
      <section aria-labelledby="collection-setup-title" aria-modal="true" className="settings-dialog collection-setup" role="dialog" ref={dialog}
        onKeyDown={event => {
          if (event.key === "Escape" && !busy) { event.stopPropagation(); onCancel(); }
          if (event.key === "Tab") {
            const controls = Array.from(dialog.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
            const first = controls[0]; const last = controls.at(-1);
            if (!first) { event.preventDefault(); return; }
            if (event.shiftKey && (document.activeElement === first || document.activeElement === heading.current)) { event.preventDefault(); last?.focus(); }
            else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
          }
        }}>
        <header className="settings-header">
          <div><span className="eyebrow">Watchcraft · Collection setup</span><h1 id="collection-setup-title" ref={heading} tabIndex={-1}>{title}</h1></div>
        </header>
        <div className="collection-setup-body" aria-busy={busy}>
          <ol className="collection-setup-steps" aria-label="Setup progress">
            {["Introduction", "Video folder", "Review"].map((label, index) => <li key={label} aria-current={index === ["intro", "folder", "review"].indexOf(step) ? "step" : undefined}>{label}</li>)}
          </ol>
          {step === "intro" && <>
            <p className="collection-setup-copy">{onboarding?.intro ?? `Explore ${collection.title}. Connect your video folder to start watching.`}</p>
            <p>Watchcraft has installed the collection’s guide and chapter information. Your videos stay where you keep them.</p>
          </>}
          {step === "folder" && <>
            <p className="collection-setup-copy">{onboarding?.media_folder_help ?? "Choose the folder containing this collection’s downloaded videos, keeping their original subfolders."}</p>
            <p>A video folder does not need a Watchcraft manifest. Watchcraft checks for matching files and never moves or deletes your videos.</p>
          </>}
          {step === "review" && <>
            <p className="collection-setup-result"><strong>{collection.mediaFound} of {collection.mediaExpected}</strong> local videos available</p>
            <p>{missing > 0 ? `${missing} videos are missing from this device. You can watch the available videos now and add the others later.` : "All expected local videos were found. You’re ready to start watching."}</p>
            {collection.mediaExtra > 0 && <p>{collection.mediaExtra} extra videos are not part of this collection and will be ignored.</p>}
            {collection.mediaRoot && <p className="collection-setup-path">{displayLocalPath(collection.mediaRoot)}</p>}
          </>}
          {notice && <p role="status">{notice}</p>}
          {error && <p className="settings-error" role="alert">{error}</p>}
          <div className="collection-setup-actions">
            <button disabled={busy} onClick={onCancel} type="button">Finish later</button>
            {step === "intro" && <button className="primary-action" onClick={() => setStep("folder")} type="button">Continue</button>}
            {step === "folder" && <>
              {canContinue && <button disabled={busy} onClick={() => setStep("review")} type="button">Review current folder</button>}
              <button className="primary-action" disabled={busy} onClick={() => void chooseFolder()} type="button">{busy ? "Checking folder…" : "Choose video folder…"}</button>
            </>}
            {step === "review" && <>
              <button disabled={busy} onClick={() => void chooseFolder()} type="button">{busy ? "Checking folder…" : "Choose another folder…"}</button>
              <button className="primary-action" disabled={busy || !canContinue} onClick={() => void finish()} type="button">{busy ? "Finishing setup…" : openAfter ? missing > 0 ? "Start watching available videos" : "Start watching" : "Save setup"}</button>
            </>}
          </div>
        </div>
      </section>
    </div>
  );
}
