export async function api<T = Record<string, unknown>>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { ...(init?.body instanceof Blob ? {} : { 'Content-Type': 'application/json' }), ...init?.headers } });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail : `操作失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}
export const jsonBody = (body: unknown, method = 'POST') => ({ method, body: JSON.stringify(body) });
export type User = { id: string; username: string; role: string };
export type Segment = { page: number; rect: number[] };
export type Question = {
  id: string; active?: number; ocr_used?: number; label: string; root_label: string; parent_label: string | null; paper_id: string; leaf: number;
  stem: string; marks: number | null; topic_auto: string[]; tags: string[]; difficulty: string; review_status: string;
  segments: Segment[]; context_segments: Segment[]; ms_segments: Segment[]; official_answer: string; official_guidance: string;
  subject_code: string; subject: string; year: number; season: string; paper_number: string; paper_level: string; calculator: string;
  saved?: number; note?: string; mastery?: string; mistakes?: number; owner_id?: string; visibility?: string;
  paper?: { owner_id: string; subject_code: string; year: number; season: string; paper_number: string; qp_file_id: string; ms_file_id: string; };
};
export type BuilderItem = { question_id: string; marks: number | null; space: number; review_status?: string };
export type AIConfig = { local_allowed: boolean; cloud_allowed: boolean; local_enabled: boolean; model: string; embedding_model: string; recommendations: boolean; cloud_enabled: boolean; cloud_available: boolean };
