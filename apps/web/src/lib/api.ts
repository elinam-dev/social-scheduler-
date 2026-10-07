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

export type CaptionStyleName = "default" | "minimal" | "word-highlight";

export interface ClipRead {
  id: string;
  video_id: string;
  start_seconds: number;
  end_seconds: number;
  rank: number | null;
  score: number | null;
  title: string | null;
  aspect_ratio: string;
  status: string;
  caption_style: CaptionStyleName;
  created_at: string;
  preview_url: string | null;
}

export interface ClipTrimUpdate {
  start_seconds: number;
  end_seconds: number;
}

export interface ClipCaptionStyleUpdate {
  caption_style: CaptionStyleName;
}

export interface VideoUploadResponse {
  video: VideoRead;
  job: JobRead;
}

export interface VideoUrlIngest {
  url: string;
  rights_confirmed: boolean;
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

function parsePayload(
  responseText: string,
  status: number,
  ok: boolean,
): unknown {
  if (!responseText) {
    if (!ok) {
      return undefined;
    }
    throw new ApiError("The API returned an empty response.", status);
  }
  try {
    return JSON.parse(responseText) as unknown;
  } catch {
    if (!ok) {
      throw new ApiError(responseText, status);
    }
    throw new ApiError("The API returned an invalid JSON response.", status);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  const responseText = await response.text();
  const payload = parsePayload(responseText, response.status, response.ok);

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

  uploadVideo(
    projectId: string,
    file: File,
    onProgress: (progress: number) => void,
  ): Promise<VideoUploadResponse> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const formData = new FormData();
      formData.append("file", file);

      xhr.open(
        "POST",
        `${apiBaseUrl}/projects/${encodeURIComponent(projectId)}/videos`,
      );
      xhr.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      });
      xhr.addEventListener("load", () => {
        let payload: unknown;
        try {
          payload = parsePayload(
            xhr.responseText,
            xhr.status,
            xhr.status >= 200 && xhr.status < 300,
          );
        } catch (error) {
          reject(error);
          return;
        }
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new ApiError(errorMessage(payload), xhr.status));
          return;
        }
        resolve(payload as VideoUploadResponse);
      });
      xhr.addEventListener("error", () => {
        reject(new ApiError("Could not connect to the local API.", 0));
      });
      xhr.addEventListener("abort", () => {
        reject(new ApiError("The upload was cancelled.", 0));
      });
      xhr.send(formData);
    });
  },

  ingestVideoUrl(
    projectId: string,
    input: VideoUrlIngest,
  ): Promise<VideoUploadResponse> {
    return request<VideoUploadResponse>(
      `/projects/${encodeURIComponent(projectId)}/videos/url`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      },
    );
  },

  jobEventsUrl(jobId: string): string {
    return `${apiBaseUrl}/jobs/${encodeURIComponent(jobId)}/events`;
  },

  getJob(jobId: string): Promise<JobRead> {
    return request<JobRead>(`/jobs/${encodeURIComponent(jobId)}`);
  },

  getClips(videoId: string): Promise<ClipRead[]> {
    return request<ClipRead[]>(
      `/videos/${encodeURIComponent(videoId)}/clips`,
    );
  },

  updateClipTrim(
    clipId: string,
    boundaries: ClipTrimUpdate,
  ): Promise<ClipRead> {
    return request<ClipRead>(`/clips/${encodeURIComponent(clipId)}/trim`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(boundaries),
    });
  },

  updateClipCaptionStyle(
    clipId: string,
    style: ClipCaptionStyleUpdate,
  ): Promise<ClipRead> {
    return request<ClipRead>(
      `/clips/${encodeURIComponent(clipId)}/caption-style`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(style),
      },
    );
  },

  renderClip(clipId: string): Promise<JobRead> {
    return request<JobRead>(`/clips/${encodeURIComponent(clipId)}/render`, {
      method: "POST",
    });
  },

  clipPreviewUrl(clipId: string): string {
    return `${apiBaseUrl}/clips/${encodeURIComponent(clipId)}/preview`;
  },

  clipDownloadUrl(clipId: string): string {
    return `${apiBaseUrl}/clips/${encodeURIComponent(clipId)}/download`;
  },

  videoClipsDownloadUrl(videoId: string): string {
    return `${apiBaseUrl}/videos/${encodeURIComponent(videoId)}/clips/download`;
  },

  getTranscript(videoId: string): Promise<Transcript> {
    return request<Transcript>(
      `/videos/${encodeURIComponent(videoId)}/transcript`,
    );
  },
};
