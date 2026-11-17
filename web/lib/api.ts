import type {
  Health,
  LiveDockResult,
  Network,
  Part,
  PlantHit,
  RunStatus,
  Shortlist,
  ValidationReport,
} from "./types";

// Same-origin by default: next.config.ts proxies /v1 to the engine, so a page
// opened through a tunnel can reach a loopback API without CORS or Chrome's
// private-network checks. Set NEXT_PUBLIC_API_URL only to bypass the proxy.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the engine at ${API_URL}. Start it with "uvicorn engine.api:app --port 8000".`,
      0,
    );
  }
  if (!response.ok) {
    let detail: unknown = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail ?? body;
    } catch {
      /* non-JSON error body */
    }
    const message =
      typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/v1/health"),
  conditions: () =>
    request<{ conditions: { name: string; label: string; targets: number }[] }>(
      "/v1/conditions",
    ),
  plants: (q: string) =>
    request<{ results: PlantHit[] }>(`/v1/plants?q=${encodeURIComponent(q)}`),
  parts: (plantId: string) =>
    request<{ plant: string; parts: Part[] }>(
      `/v1/plants/${encodeURIComponent(plantId)}/parts`,
    ),
  createRun: (body: {
    plant: string;
    part: string;
    solvent: string;
    condition: string;
    top: number;
  }) =>
    request<{ run_id: string; queue: string }>("/v1/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getRun: (runId: string) => request<RunStatus>(`/v1/runs/${runId}`),
  shortlist: (runId: string) =>
    request<Shortlist>(`/v1/runs/${runId}/shortlist`),
  network: (runId: string) => request<Network>(`/v1/runs/${runId}/network`),
  liveDock: (runId: string, body: { targets: string[]; candidates: number }) =>
    request<LiveDockResult>(`/v1/runs/${runId}/dock`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  validation: () => request<ValidationReport>("/v1/validation"),
  reportUrl: (runId: string) => `${API_URL}/v1/runs/${runId}/report.pdf`,
};
