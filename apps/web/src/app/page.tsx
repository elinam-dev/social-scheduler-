"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";

import { api, ApiError, type JobRead } from "@/lib/api";

type UploadStage = "idle" | "creating" | "uploading" | "processing" | "succeeded" | "failed";

function isTerminal(job: JobRead): boolean {
  return job.status === "succeeded" || job.status === "failed";
}

export default function Home() {
  const [projectName, setProjectName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<UploadStage>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [job, setJob] = useState<JobRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamWarning, setStreamWarning] = useState<string | null>(null);
  const eventSource = useRef<EventSource | null>(null);

  useEffect(() => () => eventSource.current?.close(), []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Choose a video file to upload.");
      return;
    }

    eventSource.current?.close();
    setError(null);
    setStreamWarning(null);
    setJob(null);
    setUploadProgress(0);
    setStage("creating");

    try {
      const project = await api.createProject({ name: projectName.trim() });
      setStage("uploading");
      const result = await api.uploadVideo(project.id, file, setUploadProgress);
      setJob(result.job);

      if (isTerminal(result.job)) {
        setStage(result.job.status === "succeeded" ? "succeeded" : "failed");
        return;
      }

      setStage("processing");
      const source = new EventSource(api.jobEventsUrl(result.job.id));
      eventSource.current = source;
      source.onmessage = (message) => {
        try {
          const update = JSON.parse(message.data) as JobRead;
          setJob(update);
          if (isTerminal(update)) {
            source.close();
            eventSource.current = null;
            setStage(update.status === "succeeded" ? "succeeded" : "failed");
          }
        } catch {
          source.close();
          eventSource.current = null;
          setError("The API sent an invalid job update.");
          setStage("failed");
        }
      };
      source.onerror = () => {
        setStreamWarning("Connection interrupted. Reconnecting to the local API…");
      };
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "The video could not be uploaded. Check that the local API is running.",
      );
      setStage("failed");
    }
  }

  const progress =
    stage === "uploading"
      ? uploadProgress
      : stage === "processing" || stage === "succeeded" || stage === "failed"
        ? (job?.progress ?? 0)
        : 0;
  const statusText =
    stage === "creating"
      ? "Creating your project…"
      : stage === "uploading"
        ? `Uploading video… ${uploadProgress}%`
        : stage === "processing"
          ? `Processing video… ${job?.progress ?? 0}%`
          : stage === "succeeded"
            ? "Video processing complete."
            : stage === "failed"
              ? "This upload did not complete."
              : "Ready when you are.";

  return (
    <main className="flex min-h-screen flex-col bg-[#f5f3ee] text-[#1e2926]">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-7">
        <Link
          href="/"
          className="flex items-center gap-3"
          aria-label="Local Clip Studio home"
        >
          <span className="grid size-10 place-items-center rounded-xl bg-[#194d40] text-lg font-semibold text-white">
            LC
          </span>
          <span className="text-sm font-semibold tracking-wide">
            LOCAL CLIP STUDIO
          </span>
        </Link>
        <span className="rounded-full border border-[#d4d8d0] px-3 py-1.5 text-xs font-medium text-[#52645d]">
          SELF-HOSTED
        </span>
      </header>

      <section className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-12 px-6 py-12 md:grid-cols-[1.05fr_0.95fr]">
        <div>
          <p className="mb-5 text-xs font-semibold tracking-[0.2em] text-[#397263]">
            YOUR FOOTAGE. YOUR MACHINE.
          </p>
          <h1 className="max-w-xl text-5xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">
            Long videos,
            <br />
            <span className="text-[#397263]">shorter stories.</span>
          </h1>
          <p className="mt-6 max-w-lg text-lg leading-8 text-[#64726b]">
            Upload a video you own or have permission to process. Your local
            pipeline will prepare it for clip selection.
          </p>
          <div className="mt-8 flex items-center gap-3 text-sm text-[#64726b]">
            <span className="size-2 rounded-full bg-[#4f9b72]" />
            Runs on your computer · No cloud account required
          </div>
        </div>

        <div className="rounded-3xl border border-[#dfe2db] bg-white p-6 shadow-[0_24px_70px_-40px_rgba(25,77,64,0.35)] sm:p-8">
          <div className="border-b border-[#edf0eb] pb-5">
            <h2 className="text-lg font-semibold">Start a project</h2>
            <p className="mt-1 text-sm text-[#78847d]">
              Choose a name and a source video.
            </p>
          </div>

          <form className="space-y-5 pt-6" onSubmit={handleSubmit}>
            <label className="block">
              <span className="mb-2 block text-sm font-medium">Project name</span>
              <input
                className="w-full rounded-xl border border-[#dfe2db] bg-white px-4 py-3 text-sm outline-none transition focus:border-[#397263] focus:ring-2 focus:ring-[#397263]/15"
                maxLength={200}
                onChange={(event) => setProjectName(event.target.value)}
                placeholder="e.g. Studio interview"
                required
                value={projectName}
              />
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium">Video file</span>
              <input
                accept="video/*,.mp4,.mov,.mkv,.webm"
                className="block w-full rounded-xl border border-[#dfe2db] bg-[#f7f8f5] px-3 py-3 text-sm text-[#52645d] file:mr-3 file:rounded-lg file:border-0 file:bg-[#e9f3ed] file:px-3 file:py-2 file:text-xs file:font-semibold file:text-[#397263]"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                required
                type="file"
              />
            </label>

            <button
              className="w-full rounded-xl bg-[#194d40] px-5 py-3.5 text-sm font-semibold text-white transition hover:bg-[#123e33] disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!file || !projectName.trim() || stage === "creating" || stage === "uploading" || stage === "processing"}
              type="submit"
            >
              {stage === "creating" || stage === "uploading" || stage === "processing"
                ? "Working…"
                : "Upload video"}
            </button>
          </form>

          <div className="mt-6" aria-live="polite" role="status">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-[#52645d]">{statusText}</span>
              {job && <span className="text-[#78847d]">{job.status}</span>}
            </div>
            {(stage === "uploading" || stage === "processing" || job) && (
              <div
                className="mt-3 h-2 overflow-hidden rounded-full bg-[#edf0eb]"
                role="progressbar"
                aria-label={stage === "uploading" ? "Video upload progress" : "Video processing progress"}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progress}
              >
                <div
                  className="h-full rounded-full bg-[#4f9b72] transition-[width]"
                  style={{ width: `${progress}%` }}
                />
              </div>
            )}
            {job?.error_message && (
              <p className="mt-3 text-sm text-red-700">{job.error_message}</p>
            )}
            {streamWarning && stage === "processing" && (
              <p className="mt-3 text-xs text-[#78847d]">{streamWarning}</p>
            )}
            {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
          </div>

          <p className="mt-6 rounded-xl bg-[#f7f8f5] px-4 py-3 text-xs leading-5 text-[#64726b]">
            Only upload video you own or have permission to process.
          </p>
        </div>
      </section>

      <footer className="mx-auto flex w-full max-w-6xl flex-wrap justify-between gap-2 px-6 py-6 text-xs text-[#78847d]">
        <span>Private by design · Runs on your computer</span>
        <span>Local Clip Studio</span>
      </footer>
    </main>
  );
}
