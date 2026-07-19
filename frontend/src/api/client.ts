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
  unread_count: number;
  opted_out: boolean;
  tags: string[];
  last_message: LastMessage;
}

export interface MediaAttachment {
  sid: string;
  content_type: string;
  url: string;
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
  media: MediaAttachment[];
  tags: string[];
  date_created: string;
  date_sent: string | null;
  date_updated: string;
}

export interface Thread {
  number: string;
  messages: ThreadMessage[];
  opted_out: boolean;
  total: number;
  page: number;
  page_size: number;
}

const TOKEN_KEY = "smspit-token";

export function getDashboardToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setDashboardToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export class UnauthorizedError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getDashboardToken();
  if (token) headers.set("X-Smspit-Token", token);
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    throw new UnauthorizedError(`${path} requires the dashboard token`);
  }
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

export function fetchNumbers(q = ""): Promise<NumberSummary[]> {
  const suffix = q ? `?q=${encodeURIComponent(q)}` : "";
  return request<NumberSummary[]>(`/api/numbers${suffix}`);
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

export interface AutoTagRule {
  tag: string;
  to_suffix?: string;
  from_suffix?: string;
  body_regex?: string;
}

export interface SettingsData {
  auto_tag_rules: AutoTagRule[];
  retention_max_age_hours: number;
  retention_max_messages: number;
  real_account_sid: string;
  real_auth_token: string;
  real_from_number: string;
  release_allowlist: string[];
  auto_forward_to: string;
  capture_webhook_url: string;
  inbound_webhook_url: string | null;
  inbound_webhook_method: string;
  account_sid: string;
  auth_token: string;
  simulate_delivery: boolean;
  status_delay_ms: number;
  failure_rate: number;
  forced_rules: ForcedRule[];
  strict_auth: boolean;
  strict_validation: boolean;
  enforce_optouts: boolean;
  trial_mode: boolean;
  verified_numbers: string[];
  rate_limit_per_minute: number;
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
  method: string;
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

export interface WebhookLogFilters {
  kind?: string;
  result?: string;
  message_sid?: string;
}

export function fetchWebhookLog(
  filters: WebhookLogFilters = {},
  page = 0,
): Promise<WebhookLog> {
  const params = new URLSearchParams({ page: String(page) });
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.result) params.set("result", filters.result);
  if (filters.message_sid) params.set("message_sid", filters.message_sid);
  return request<WebhookLog>(`/api/webhook-log?${params}`);
}

export function retryWebhook(id: number): Promise<WebhookDelivery> {
  return request<WebhookDelivery>(`/api/webhook-log/${id}/retry`, {
    method: "POST",
  });
}

export interface ReplyPayload {
  body: string;
  to?: string;
  media_urls?: string[];
}

export function sendReply(
  number: string,
  payload: ReplyPayload,
): Promise<ThreadMessage> {
  return request<ThreadMessage>(
    `/api/numbers/${encodeURIComponent(number)}/reply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export interface LatestCode {
  code: string;
  message_sid: string;
  body: string;
  date_created: string;
  age_seconds: number;
}

export async function fetchLatestCode(
  number: string,
): Promise<LatestCode | null> {
  const headers = new Headers();
  const token = getDashboardToken();
  if (token) headers.set("X-Smspit-Token", token);
  const response = await fetch(
    `/api/numbers/${encodeURIComponent(number)}/latest-code`,
    { headers },
  );
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`latest-code failed: ${response.status}`);
  return response.json() as Promise<LatestCode>;
}

export interface VerificationInfo {
  sid: string;
  service_sid: string;
  service_name: string;
  status: string;
  code: string;
  check_attempts: number;
  send_attempts: number;
  expires_in_seconds: number;
  date_created: string;
}

export function fetchVerifications(
  number: string,
): Promise<VerificationInfo[]> {
  return request<VerificationInfo[]>(
    `/api/numbers/${encodeURIComponent(number)}/verifications`,
  );
}

export function setOptOut(recipient: string, optedOut: boolean): Promise<void> {
  return request<void>("/api/optouts", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipient, opted_out: optedOut }),
  });
}

export function markThreadRead(number: string): Promise<void> {
  return request<void>(`/api/numbers/${encodeURIComponent(number)}/read`, {
    method: "POST",
  });
}

export interface TagCount {
  tag: string;
  count: number;
}

export function fetchTags(): Promise<TagCount[]> {
  return request<TagCount[]>("/api/tags");
}

export function setMessageTags(
  sid: string,
  tags: string[],
): Promise<{ sid: string; tags: string[] }> {
  return request(`/api/messages/${sid}/tags`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });
}

export interface EncodingCheck {
  encoding: string;
  length: number;
  num_segments: number;
  non_gsm_chars: { char: string; index: number }[];
  smart_encoding_would_use: string;
  smart_encoding_segments: number;
}

export interface MessageDetail {
  message: ThreadMessage;
  twilio: Record<string, unknown>;
  raw_params: Record<string, unknown>;
  encoding_check: EncodingCheck;
}

export interface ReleaseResult {
  released: boolean;
  to: string;
  from: string;
  real_sid: string | null;
  response_status: number | null;
  error: string | null;
}

export async function releaseMessage(
  sid: string,
  to?: string,
): Promise<ReleaseResult> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const token = getDashboardToken();
  if (token) headers.set("X-Smspit-Token", token);
  const response = await fetch(`/api/messages/${sid}/release`, {
    method: "POST",
    headers,
    body: JSON.stringify(to ? { to } : {}),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? `release failed: ${response.status}`);
  }
  return data as ReleaseResult;
}

export function fetchMessageDetail(sid: string): Promise<MessageDetail> {
  return request<MessageDetail>(`/api/messages/${sid}`);
}

export function deleteMessage(sid: string): Promise<void> {
  return request<void>(`/api/messages/${sid}`, { method: "DELETE" });
}

export interface ScheduledMessage extends ThreadMessage {
  send_at: string;
}

export function fetchScheduled(): Promise<ScheduledMessage[]> {
  return request<ScheduledMessage[]>("/api/scheduled");
}

export function cancelScheduled(sid: string): Promise<ThreadMessage> {
  return request<ThreadMessage>(`/api/scheduled/${sid}/cancel`, {
    method: "POST",
  });
}

export function exportUrl(format: "json" | "csv", number?: string): string {
  const params = new URLSearchParams({ format });
  if (number) params.set("number", number);
  const token = getDashboardToken();
  if (token) params.set("token", token);
  return `/api/export?${params}`;
}
