export interface Health {
  status: string;
  service: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    throw new Error(
      `${init?.method ?? "GET"} ${path} failed: ${response.status}`,
    );
  }
  return response.json() as Promise<T>;
}

export function fetchHealth(): Promise<Health> {
  return request<Health>("/api/health");
}
