"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";

import {
  api,
  ApiError,
  type CaptionStyleName,
  type ClipRead,
  type JobRead,
  type Transcript,
} from "@/lib/api";

type UploadStage = "idle" | "creating" | "uploading" | "processing" | "succeeded" | "failed";

const CAPTION_STYLE_OPTIONS: {
  value: CaptionStyleName;
  label: string;
  description: string;
}[] = [
  {
    value: "default",
    label: "Default",
    description: "Bold, outlined captions with a dark backing.",
  },
  {
    value: "minimal",
    label: "Minimal",
    description: "Smaller captions with a lighter outline.",
  },
  {
    value: "word-highlight",
    label: "Word highlight",
    description: "Highlights each spoken word as it appears.",
  },
];

function isTerminal(job: JobRead): boolean {
  return job.status === "succeeded" || job.status === "failed";
}

function formatClipTime(seconds: number): string {
  const wholeSeconds = Math.floor(seconds);
  const minutes = Math.floor(wholeSeconds / 60);
  const remainingSeconds = wholeSeconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

export default function Home() {
  const [projectName, setProjectName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<UploadStage>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [job, setJob] = useState<JobRead | null>(null);
  const [videoId, setVideoId] = useState<string | null>(null);
  const [clips, setClips] = useState<ClipRead[] | null>(null);
  const [editingClipId, setEditingClipId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [trimStartSeconds, setTrimStartSeconds] = useState("");
  const [trimEndSeconds, setTrimEndSeconds] = useState("");
  const [trimSaving, setTrimSaving] = useState(false);
  const [trimError, setTrimError] = useState<string | null>(null);
  const [trimNotice, setTrimNotice] = useState<string | null>(null);
  const [styleSavingClipId, setStyleSavingClipId] = useState<string | null>(null);
  const [styleError, setStyleError] = useState<string | null>(null);
  const [styleNotice, setStyleNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clipError, setClipError] = useState<string | null>(null);
  const [streamWarning, setStreamWarning] = useState<string | null>(null);
  const eventSource = useRef<EventSource | null>(null);
  const transcriptRequestId = useRef(0);

  useEffect(() => () => eventSource.current?.close(), []);

  async function loadClips(id: string) {
    setClipError(null);
    try {
      setClips(await api.getClips(id));
    } catch (cause) {
      setClipError(
        cause instanceof ApiError
          ? cause.message
          : "Could not load clips from the local API.",
      );
    }
  }

  async function openTrimEditor(clip: ClipRead) {
    const requestId = ++transcriptRequestId.current;
    setEditingClipId(clip.id);
    setTrimStartSeconds(String(clip.start_seconds));
    setTrimEndSeconds(String(clip.end_seconds));
    setTranscript(null);
    setTranscriptLoading(true);
    setTrimError(null);
    setTrimNotice(null);

    try {
      const result = await api.getTranscript(clip.video_id);
      if (requestId === transcriptRequestId.current) {
        setTranscript(result);
      }
    } catch (cause) {
      if (requestId === transcriptRequestId.current) {
        setTrimError(
          cause instanceof ApiError
            ? cause.message
            : "Could not load the transcript from the local API.",
        );
      }
    } finally {
      if (requestId === transcriptRequestId.current) {
        setTranscriptLoading(false);
      }
    }
  }

  function closeTrimEditor() {
    transcriptRequestId.current += 1;
    setEditingClipId(null);
    setTranscript(null);
    setTranscriptLoading(false);
  }

  async function saveClipTrim(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clip = clips?.find((candidate) => candidate.id === editingClipId);
    const startSeconds = Number(trimStartSeconds);
    const endSeconds = Number(trimEndSeconds);
    if (!clip) {
      setTrimError("Select a clip before saving its trim.");
      return;
    }
    if (
      !Number.isFinite(startSeconds) ||
      !Number.isFinite(endSeconds) ||
      startSeconds < 0 ||
      endSeconds <= startSeconds
    ) {
      setTrimError("End time must be greater than the non-negative start time.");
      return;
    }

    setTrimSaving(true);
    setTrimError(null);
    try {
      const updated = await api.updateClipTrim(clip.id, {
        start_seconds: startSeconds,
        end_seconds: endSeconds,
      });
      setClips((current) =>
        current?.map((item) => (item.id === updated.id ? updated : item)) ?? null,
      );
      closeTrimEditor();
      setTrimNotice(
        "Trim saved. Render the clip again to update its preview.",
      );
    } catch (cause) {
      setTrimError(
        cause instanceof ApiError
          ? cause.message
          : "Could not save the clip trim to the local API.",
      );
    } finally {
      setTrimSaving(false);
    }
  }

  async function saveCaptionStyle(
    clip: ClipRead,
    captionStyle: CaptionStyleName,
  ) {
    setStyleSavingClipId(clip.id);
    setStyleError(null);
    setStyleNotice(null);
    try {
      const updated = await api.updateClipCaptionStyle(clip.id, {
        caption_style: captionStyle,
      });
      setClips((current) =>
        current?.map((item) => (item.id === updated.id ? updated : item)) ?? null,
      );
      setStyleNotice(
        "Caption style saved. Render the clip again to apply it.",
      );
    } catch (cause) {
      setStyleError(
        cause instanceof ApiError
          ? cause.message
          : "Could not save the caption style to the local API.",
      );
    } finally {
      setStyleSavingClipId(null);
    }
  }

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
    setVideoId(null);
    setClips(null);
    setClipError(null);
    closeTrimEditor();
    setTrimError(null);
    setTrimNotice(null);
    setStyleError(null);
    setStyleNotice(null);
    setUploadProgress(0);
    setStage("creating");

    try {
      const project = await api.createProject({ name: projectName.trim() });
      setStage("uploading");
      const result = await api.uploadVideo(project.id, file, setUploadProgress);
      setJob(result.job);
      setVideoId(result.video.id);

      if (isTerminal(result.job)) {
        setStage(result.job.status === "succeeded" ? "succeeded" : "failed");
        if (result.job.status === "succeeded") {
          void loadClips(result.video.id);
        }
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
            if (update.status === "succeeded" && update.video_id) {
              void loadClips(update.video_id);
            }
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
  const editingClip =
    clips?.find((clip) => clip.id === editingClipId) ?? null;

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

      {videoId && (
        <section className="mx-auto w-full max-w-6xl px-6 pb-14">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs font-semibold tracking-[0.18em] text-[#397263]">
                VIDEO RESULTS
              </p>
              <h2 className="mt-2 text-2xl font-semibold">Your clips</h2>
            </div>
            <p className="text-sm text-[#78847d]">
              Ranked previews appear here when available.
            </p>
          </div>

          {stage === "processing" && (
            <p className="rounded-2xl border border-[#dfe2db] bg-white p-6 text-sm text-[#64726b]">
              Processing your video. Clips will be listed here when processing
              finishes.
            </p>
          )}
          {stage === "succeeded" && clips === null && !clipError && (
            <p className="rounded-2xl border border-[#dfe2db] bg-white p-6 text-sm text-[#64726b]">
              Loading clips…
            </p>
          )}
          {clipError && (
            <p
              className="rounded-2xl border border-red-200 bg-white p-6 text-sm text-red-700"
              role="alert"
            >
              {clipError}
            </p>
          )}
          {stage === "succeeded" && clips?.length === 0 && (
            <p className="rounded-2xl border border-[#dfe2db] bg-white p-6 text-sm text-[#64726b]">
              No rendered clips are available for this video yet.
            </p>
          )}
          {stage === "failed" && !clipError && (
            <p className="rounded-2xl border border-[#dfe2db] bg-white p-6 text-sm text-[#64726b]">
              Video processing failed, so no clips are available.
            </p>
          )}
          {clips && clips.length > 0 && (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {clips.map((clip, index) => (
                <article
                  className="overflow-hidden rounded-2xl border border-[#dfe2db] bg-white shadow-sm"
                  key={clip.id}
                >
                  {clip.preview_url ? (
                    <video
                      aria-label={`Preview: Clip ${clip.rank ?? index + 1}`}
                      className={`w-full bg-[#1e2926] object-contain ${
                        clip.aspect_ratio === "1:1"
                          ? "aspect-square"
                          : clip.aspect_ratio === "16:9"
                            ? "aspect-video"
                            : "aspect-[9/16]"
                      }`}
                      controls
                      preload="metadata"
                      src={api.clipPreviewUrl(clip.id)}
                    />
                  ) : (
                    <div className="grid aspect-[9/16] w-full place-items-center bg-[#e9ede8] px-6 text-center text-sm text-[#64726b]">
                      Preview unavailable
                    </div>
                  )}
                  <div className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="font-semibold">
                        {clip.title ?? `Clip ${clip.rank ?? index + 1}`}
                      </h3>
                      <div className="flex shrink-0 gap-2">
                        <span className="rounded-full bg-[#f1f2ef] px-2.5 py-1 text-xs font-medium text-[#64726b]">
                          {clip.status}
                        </span>
                        <span className="rounded-full bg-[#e9f3ed] px-2.5 py-1 text-xs font-semibold text-[#397263]">
                          {clip.score === null
                            ? "Unscored"
                            : `${Math.round(clip.score * 100)}% score`}
                        </span>
                      </div>
                    </div>
                    <p className="mt-2 text-xs text-[#78847d]">
                      {formatClipTime(clip.start_seconds)}–{formatClipTime(clip.end_seconds)}
                      {" · "}
                      {Math.round(clip.end_seconds - clip.start_seconds)} sec
                    </p>
                    <button
                      className="mt-4 rounded-lg border border-[#d4d8d0] px-3 py-2 text-xs font-semibold text-[#397263] transition hover:bg-[#f5f8f4] disabled:opacity-50"
                      disabled={trimSaving || clip.status === "rendering"}
                      onClick={() => void openTrimEditor(clip)}
                      type="button"
                    >
                      Edit trim
                    </button>
                    <label className="mt-4 block text-xs font-semibold text-[#52645d]">
                      Caption style
                      <select
                        className="mt-2 w-full rounded-lg border border-[#dfe2db] bg-white px-3 py-2 text-sm font-normal"
                        disabled={
                          styleSavingClipId !== null ||
                          clip.status === "rendering"
                        }
                        onChange={(event) => {
                          const selected = CAPTION_STYLE_OPTIONS.find(
                            (option) => option.value === event.target.value,
                          );
                          if (selected) {
                            void saveCaptionStyle(clip, selected.value);
                          }
                        }}
                        value={clip.caption_style}
                      >
                        {CAPTION_STYLE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <span className="mt-2 block font-normal text-[#78847d]">
                        {
                          CAPTION_STYLE_OPTIONS.find(
                            (option) => option.value === clip.caption_style,
                          )?.description
                        }
                      </span>
                    </label>
                  </div>
                </article>
              ))}
            </div>
          )}
          {trimNotice && (
            <p
              className="mt-5 rounded-xl bg-[#e9f3ed] px-4 py-3 text-sm text-[#397263]"
              role="status"
            >
              {trimNotice}
            </p>
          )}
          {styleError && (
            <p
              className="mt-5 rounded-xl border border-red-200 bg-white px-4 py-3 text-sm text-red-700"
              role="alert"
            >
              {styleError}
            </p>
          )}
          {styleNotice && (
            <p
              className="mt-5 rounded-xl bg-[#e9f3ed] px-4 py-3 text-sm text-[#397263]"
              role="status"
            >
              {styleNotice}
            </p>
          )}
          {editingClipId && (
            <div className="mt-6 rounded-2xl border border-[#dfe2db] bg-white p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold tracking-[0.16em] text-[#397263]">
                    TRANSCRIPT TRIM
                  </p>
                  <h3 className="mt-2 text-lg font-semibold">
                    {editingClip?.title ??
                      `Clip ${editingClip?.rank ?? ""}`}
                  </h3>
                </div>
                <button
                  className="rounded-lg border border-[#d4d8d0] px-3 py-2 text-xs font-semibold text-[#64726b] disabled:opacity-50"
                  disabled={trimSaving}
                  onClick={closeTrimEditor}
                  type="button"
                >
                  Close editor
                </button>
              </div>
              {transcriptLoading && (
                <p className="mt-4 text-sm text-[#64726b]">
                  Loading transcript…
                </p>
              )}
              {trimError && (
                <p className="mt-4 text-sm text-red-700" role="alert">
                  {trimError}
                </p>
              )}
              {transcript && editingClip && (
                <div className="mt-5 grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
                  <form className="space-y-4" onSubmit={saveClipTrim}>
                    <p className="text-sm leading-6 text-[#64726b]">
                      Set boundaries from transcript segments or enter exact
                      seconds. The clip must remain within the source video.
                    </p>
                    <label className="block text-sm font-medium">
                      Start time (seconds)
                      <input
                        className="mt-2 w-full rounded-lg border border-[#dfe2db] px-3 py-2"
                        max={transcript.duration_seconds}
                        min={0}
                        onChange={(event) =>
                          setTrimStartSeconds(event.target.value)
                        }
                        required
                        step="0.01"
                        type="number"
                        value={trimStartSeconds}
                      />
                    </label>
                    <label className="block text-sm font-medium">
                      End time (seconds)
                      <input
                        className="mt-2 w-full rounded-lg border border-[#dfe2db] px-3 py-2"
                        max={transcript.duration_seconds}
                        min={0}
                        onChange={(event) =>
                          setTrimEndSeconds(event.target.value)
                        }
                        required
                        step="0.01"
                        type="number"
                        value={trimEndSeconds}
                      />
                    </label>
                    <button
                      className="rounded-lg bg-[#194d40] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                      disabled={trimSaving}
                      type="submit"
                    >
                      {trimSaving ? "Saving…" : "Save trim"}
                    </button>
                  </form>
                  <div
                    aria-label="Transcript boundary choices"
                    className="max-h-96 space-y-3 overflow-y-auto rounded-xl bg-[#f7f8f5] p-4"
                  >
                    {transcript.segments.length === 0 ? (
                      <p className="text-sm text-[#64726b]">
                        No transcript segments are available.
                      </p>
                    ) : (
                      transcript.segments.map((segment, index) => (
                        <div
                          className="border-b border-[#e4e8e1] pb-3 last:border-0"
                          key={`${segment.start_seconds}-${index}`}
                        >
                          <p className="text-sm leading-6 text-[#35443e]">
                            {segment.text}
                          </p>
                          <div className="mt-2 flex gap-2">
                            <button
                              className="rounded-md border border-[#d4d8d0] bg-white px-2.5 py-1.5 text-xs font-medium text-[#397263]"
                              onClick={() =>
                                setTrimStartSeconds(
                                  String(segment.start_seconds),
                                )
                              }
                              type="button"
                            >
                              Set start {formatClipTime(segment.start_seconds)}
                            </button>
                            <button
                              className="rounded-md border border-[#d4d8d0] bg-white px-2.5 py-1.5 text-xs font-medium text-[#397263]"
                              onClick={() =>
                                setTrimEndSeconds(String(segment.end_seconds))
                              }
                              type="button"
                            >
                              Set end {formatClipTime(segment.end_seconds)}
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      <footer className="mx-auto flex w-full max-w-6xl flex-wrap justify-between gap-2 px-6 py-6 text-xs text-[#78847d]">
        <span>Private by design · Runs on your computer</span>
        <span>Local Clip Studio</span>
      </footer>
    </main>
  );
}
