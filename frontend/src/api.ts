export type Orientation = "vertical" | "horizontal";

export interface JobRequest {
  topic: string;
  scenes: number;
  orientation: Orientation;
  voice: string;
  music: boolean;
  captions: boolean;
}

export type Step = "queued" | "script" | "voice" | "visuals" | "captions" | "music" | "render" | "done";

export interface SceneInfo {
  narration: string;
  keywords: string;
}

export interface Job {
  id: string;
  topic: string;
  status: "running" | "done" | "error";
  step: Step;
  progress: number;
  message: string;
  title?: string;
  scenes?: SceneInfo[];
  video_url?: string;
  duration?: number;
  error?: string;
  notes: { script?: string; voice?: string; visuals?: string };
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export const createJob = (req: JobRequest): Promise<Job> =>
  fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  }).then((r) => json<Job>(r));

export const getJob = (id: string): Promise<Job> => fetch(`/api/jobs/${id}`).then((r) => json<Job>(r));
