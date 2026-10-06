import Link from "next/link";

export default function Home() {
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

      <section className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-12 px-6 py-16 md:grid-cols-[1.1fr_0.9fr]">
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
            Find the moments worth sharing. Create captioned vertical clips
            from videos you own, with a workflow designed to run locally.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            <span className="rounded-xl bg-[#194d40] px-5 py-3 text-sm font-semibold text-white">
              Upload workspace coming next
            </span>
            <span className="text-sm text-[#64726b]">
              No cloud account required
            </span>
          </div>
        </div>

        <div className="rounded-3xl border border-[#dfe2db] bg-white p-6 shadow-[0_24px_70px_-40px_rgba(25,77,64,0.35)]">
          <div className="flex items-center justify-between border-b border-[#edf0eb] pb-5">
            <div>
              <p className="text-sm font-semibold">Clip pipeline</p>
              <p className="mt-1 text-xs text-[#78847d]">Local processing status</p>
            </div>
            <span className="flex items-center gap-2 rounded-full bg-[#e9f3ed] px-3 py-1.5 text-xs font-medium text-[#397263]">
              <span className="size-2 rounded-full bg-[#4f9b72]" />
              Ready
            </span>
          </div>
          <ol className="space-y-5 pt-6">
            {[
              ["01", "Transcribe", "Word-level timestamps"],
              ["02", "Find moments", "Ranked clip candidates"],
              ["03", "Reframe & caption", "Vertical exports, locally"],
            ].map(([number, title, description]) => (
              <li key={number} className="flex items-start gap-4">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[#f0f3ef] text-xs font-semibold text-[#397263]">
                  {number}
                </span>
                <span>
                  <span className="block text-sm font-semibold">{title}</span>
                  <span className="mt-1 block text-xs text-[#78847d]">
                    {description}
                  </span>
                </span>
              </li>
            ))}
          </ol>
          <div className="mt-7 rounded-xl bg-[#f7f8f5] px-4 py-3 text-xs leading-5 text-[#64726b]">
            Only upload video you own or have permission to process.
          </div>
        </div>
      </section>

      <footer className="mx-auto flex w-full max-w-6xl flex-wrap justify-between gap-2 px-6 py-6 text-xs text-[#78847d]">
        <span>Private by design · Runs on your computer</span>
        <span>Local Clip Studio</span>
      </footer>
    </main>
  );
}
