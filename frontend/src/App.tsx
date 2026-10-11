import { useEffect, useState } from "react";
import { createJob, getJob, type Job, type JobRequest, type Step } from "./api";

const STAGES: { key: Step; label: string }[] = [
  { key: "script", label: "Script" },
  { key: "voice", label: "Voiceover" },
  { key: "visuals", label: "Footage" },
  { key: "captions", label: "Captions" },
  { key: "music", label: "Music" },
  { key: "render", label: "Render" },
];

const VOICES = [
  { id: "en-US-AndrewNeural", label: "Andrew, warm" },
  { id: "en-US-AriaNeural", label: "Aria, bright" },
  { id: "en-GB-RyanNeural", label: "Ryan, British" },
  { id: "en-AU-NatashaNeural", label: "Natasha, Australian" },
];

const EXAMPLES = ["Why octopuses are so smart", "How the Panama Canal works", "The rise of the espresso machine"];

export default function App() {
  const [form, setForm] = useState<JobRequest>({
    topic: "",
    scenes: 5,
    orientation: "vertical",
    voice: VOICES[0].id,
    music: true,
    captions: true,
  });
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const running = submitting || job?.status === "running";
  const set = <K extends keyof JobRequest>(k: K, v: JobRequest[K]) => setForm((f) => ({ ...f, [k]: v }));

  // Poll the job while it runs.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const t = setInterval(async () => {
      try {
        setJob(await getJob(job.id));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Lost connection to the server");
      }
    }, 1000);
    return () => clearInterval(t);
  }, [job?.id, job?.status]);

  async function submit() {
    setError(null);
    setSubmitting(true);
    setJob(null);
    try {
      setJob(await createJob({ ...form, topic: form.topic.trim() }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the server. Is the backend running on port 8000?");
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = form.topic.trim().length >= 3 && !running;

  return (
    <div className="app">
      <header className="top">
        <span className="mark">Autocut</span>
        <span className="tag">Topic in, video out</span>
      </header>

      <main className="grid">
        <section className="controls" aria-label="Video settings">
          <label className="topic">
            <span className="sr">Topic</span>
            <textarea
              value={form.topic}
              onChange={(e) => set("topic", e.target.value)}
              placeholder="What should the video be about?"
              rows={3}
              maxLength={200}
              disabled={running}
            />
          </label>
          <div className="examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="chip" onClick={() => set("topic", ex)} disabled={running}>
                {ex}
              </button>
            ))}
          </div>

          <div className="row">
            <fieldset disabled={running}>
              <legend>Format</legend>
              <div className="seg">
                {(["vertical", "horizontal"] as const).map((o) => (
                  <button
                    key={o}
                    type="button"
                    className={form.orientation === o ? "on" : ""}
                    aria-pressed={form.orientation === o}
                    onClick={() => set("orientation", o)}
                  >
                    {o === "vertical" ? "9:16 Shorts" : "16:9 Wide"}
                  </button>
                ))}
              </div>
            </fieldset>
            <label className="field">
              <span>Scenes: {form.scenes}</span>
              <input
                type="range"
                min={2}
                max={8}
                value={form.scenes}
                disabled={running}
                onChange={(e) => set("scenes", Number(e.target.value))}
              />
            </label>
          </div>

          <div className="row">
            <label className="field">
              <span>Voice</span>
              <select value={form.voice} disabled={running} onChange={(e) => set("voice", e.target.value)}>
                {VOICES.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="checks">
              <label>
                <input type="checkbox" checked={form.captions} disabled={running} onChange={(e) => set("captions", e.target.checked)} />
                Burned-in captions
              </label>
              <label>
                <input type="checkbox" checked={form.music} disabled={running} onChange={(e) => set("music", e.target.checked)} />
                Background music
              </label>
            </div>
          </div>

          <button className="go" type="button" onClick={submit} disabled={!canSubmit}>
            {running ? "Generating…" : "Generate video"}
          </button>
          {error && <p className="err" role="alert">{error}</p>}

          {job?.scenes && (
            <ol className="shots" aria-label="Shot list">
              {job.scenes.map((s, i) => (
                <li key={i}>
                  <p>{s.narration}</p>
                  <small>Footage search: {s.keywords}</small>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="stage" aria-label="Preview">
          <div className={`frame ${form.orientation}`}>
            <FrameBody job={job} submitting={submitting} />
          </div>

          <ol className="stages">
            {STAGES.map((s) => (
              <li key={s.key} className={stageState(job, s.key)}>
                {s.label}
              </li>
            ))}
          </ol>

          {job?.status === "done" && job.video_url && (
            <div className="done">
              <a className="dl" href={job.video_url} download={`${slug(job.title ?? job.topic)}.mp4`}>
                Download mp4
              </a>
              <span className="meta">
                {job.duration}s · script {job.notes.script} · voice {job.notes.voice} · footage {job.notes.visuals}
              </span>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function FrameBody({ job, submitting }: { job: Job | null; submitting: boolean }) {
  if (job?.status === "done" && job.video_url) {
    return <video key={job.video_url} src={job.video_url} controls autoPlay playsInline />;
  }
  if (job?.status === "error") {
    return (
      <div className="msg">
        <strong>Generation failed</strong>
        <p>{job.error}</p>
      </div>
    );
  }
  if (job || submitting) {
    const pct = Math.round((job?.progress ?? 0) * 100);
    return (
      <div className="msg">
        <div className="count">{pct}</div>
        <p>{job?.message ?? "Starting"}</p>
        <div className="bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }
  return (
    <div className="msg idle">
      <p>Your video shows up here. Enter a topic and generate.</p>
    </div>
  );
}

function stageState(job: Job | null, key: Step): string {
  if (!job) return "";
  if (job.status === "done") return "done";
  const order = STAGES.map((s) => s.key);
  const cur = order.indexOf(job.step as Step);
  const idx = order.indexOf(key);
  if (cur < 0) return "";
  return idx < cur ? "done" : idx === cur ? "active" : "";
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "video";
