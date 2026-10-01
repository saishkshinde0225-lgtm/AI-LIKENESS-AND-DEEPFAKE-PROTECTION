export default function Home() {
  return (
    <main className="flex min-h-screen items-center bg-background px-6 py-16 text-foreground">
      <div className="mx-auto w-full max-w-4xl border-l-2 border-emerald-700 pl-6 sm:pl-8">
        <p className="mb-4 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-emerald-800">
          Identity Security
        </p>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
          AI Likeness Protection
        </h1>
        <p className="mt-4 max-w-xl text-base leading-7 text-neutral-600">
          Consent-based identity protection and deepfake incident management.
        </p>
      </div>
    </main>
  );
}
