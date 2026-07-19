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

export interface ForcedRule {
  to_suffix: string;
  status: string;
  error_code: number;
}

export interface SettingsData {
  inbound_webhook_url: string | null;
  inbound_webhook_method: string;
  account_sid: string;
  auth_token: string;
  simulate_delivery: boolean;
  status_delay_ms: number;
  failure_rate: number;
  forced_rules: ForcedRule[];
}

export function fetchSettings(): Promise<SettingsData> {
  return request<SettingsData>("/api/settings");
}

export function updateSettings(
  payload: Partial<SettingsData>,
): Promise<SettingsData> {
  return request<SettingsData>("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export interface WebhookDelivery {
  id: number;
  kind: string;
  url: string;
  request_params: Record<string, string>;
  response_status: number | null;
  response_body: string | null;
  duration_ms: number;
  error: string | null;
  message_sid: string | null;
  created_at: string;
}

export interface WebhookLog {
  deliveries: WebhookDelivery[];
  total: number;
  page: number;
  page_size: number;
}

export function fetchWebhookLog(page = 0): Promise<WebhookLog> {
  return request<WebhookLog>(`/api/webhook-log?page=${page}`);
}

export function retryWebhook(id: number): Promise<WebhookDelivery> {
  return request<WebhookDelivery>(`/api/webhook-log/${id}/retry`, {
    method: "POST",
  });
}
