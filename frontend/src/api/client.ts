export interface Health {
  status: string;
  service: string;
}

export interface LastMessage {
  sid: string;
  body: string;
  direction: string;
  status: string;
  date_created: string;
}

export interface NumberSummary {
  number: string;
  message_count: number;
  last_message: LastMessage;
}

export interface ThreadMessage {
  sid: string;
  direction: string;
  from_number: string;
  to_number: string;
  body: string;
  status: string;
  error_code: number | null;
  error_message: string | null;
  num_segments: number;
  num_media: number;
  encoding: string;
  channel: string;
  date_created: string;
  date_sent: string | null;
  date_updated: string;
}

export interface Thread {
  number: string;
  messages: ThreadMessage[];
  total: number;
  page: number;
  page_size: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(
      `${init?.method ?? "GET"} ${path} failed: ${response.status}`,
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export function fetchHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function fetchNumbers(): Promise<NumberSummary[]> {
  return request<NumberSummary[]>("/api/numbers");
}

export function fetchThread(number: string, page = 0): Promise<Thread> {
  return request<Thread>(
    `/api/numbers/${encodeURIComponent(number)}/messages?page=${page}`,
  );
}

export function clearThread(number: string): Promise<void> {
  return request<void>(`/api/numbers/${encodeURIComponent(number)}/messages`, {
    method: "DELETE",
  });
}

export function clearAllMessages(): Promise<void> {
  return request<void>("/api/messages", { method: "DELETE" });
}
