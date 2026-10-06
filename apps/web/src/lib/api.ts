export interface ProjectCreate {
  name: string;
  description?: string | null;
}

export interface ProjectRead {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface VideoRead {
  id: string;
  project_id: string;
  original_filename: string;
  content_type: string | null;
  size_bytes: number;
  status: string;
  created_at: string;
}

export interface JobRead {
  id: string;
  video_id: string | null;
  job_type: string;
  status: string;
  progress: number;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface VideoUploadResponse {
  video: VideoRead;
  job: JobRead;
}

export interface TranscriptWord {
  start_seconds: number;
  end_seconds: number;
  text: string;
  probability: number | null;
  speaker_id: string | null;
}

export interface TranscriptSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
  words: TranscriptWord[];
}

export interface Transcript {
  language: string;
  language_probability: number;
  duration_seconds: number;
  segments: TranscriptSegment[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "/backend-api").replace(
  /\/$/,
  "",
);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  const responseText = await response.text();
  let payload: unknown;

  if (responseText) {
    try {
      payload = JSON.parse(responseText) as unknown;
    } catch {
      if (!response.ok) {
        throw new ApiError(responseText, response.status);
      }
      throw new ApiError("The API returned an invalid JSON response.", response.status);
    }
  }

  if (!response.ok) {
    throw new ApiError(errorMessage(payload), response.status);
  }
  if (payload === undefined) {
    throw new ApiError("The API returned an empty response.", response.status);
  }
  return payload as T;
}

function errorMessage(payload: unknown): string {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "detail" in payload
  ) {
    const detail = payload.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (detail !== undefined) {
      return JSON.stringify(detail);
    }
  }
  return "The API request failed.";
}

export const api = {
  createProject(input: ProjectCreate): Promise<ProjectRead> {
    return request<ProjectRead>("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  },

  uploadVideo(projectId: string, file: File): Promise<VideoUploadResponse> {
    const formData = new FormData();
    formData.append("file", file);
    return request<VideoUploadResponse>(
      `/projects/${encodeURIComponent(projectId)}/videos`,
      { method: "POST", body: formData },
    );
  },

  getJob(jobId: string): Promise<JobRead> {
    return request<JobRead>(`/jobs/${encodeURIComponent(jobId)}`);
  },

  getTranscript(videoId: string): Promise<Transcript> {
    return request<Transcript>(
      `/videos/${encodeURIComponent(videoId)}/transcript`,
    );
  },
};
