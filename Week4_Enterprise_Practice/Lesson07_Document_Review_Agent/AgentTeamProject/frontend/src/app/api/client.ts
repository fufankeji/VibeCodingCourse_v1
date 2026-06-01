const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1';

export interface ApiError {
  error_code: string;
  message: string;
  request_id?: string;
}

class ApiClient {
  private baseUrl: string;
  private userId: string = 'anonymous';
  private userRole: string = 'reviewer';

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  setUser(userId: string, role: string) {
    this.userId = userId;
    this.userRole = role;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'X-User-ID': this.userId,
      'X-User-Role': this.userRole,
      ...(options.headers as Record<string, string> ?? {}),
    };

    // Don't set Content-Type for FormData (browser sets boundary automatically)
    if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }

    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });

    if (!res.ok) {
      let apiError: ApiError;
      try {
        const payload = await res.json();
        const detail = payload?.detail;
        if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
          apiError = detail;
        } else if (typeof detail === 'string') {
          apiError = { error_code: 'HTTP_ERROR', message: detail };
        } else {
          apiError = payload;
        }
      } catch {
        apiError = { error_code: 'UNKNOWN', message: `HTTP ${res.status}: ${res.statusText}` };
      }
      throw apiError;
    }

    // Handle 204 No Content
    if (res.status === 204) return undefined as T;

    return res.json();
  }

  get<T>(path: string) {
    return this.request<T>(path);
  }

  post<T>(path: string, body?: unknown, extraHeaders?: Record<string, string>) {
    const isFormData = body instanceof FormData;
    return this.request<T>(path, {
      method: 'POST',
      body: isFormData ? body : body ? JSON.stringify(body) : undefined,
      headers: extraHeaders,
    });
  }

  patch<T>(path: string, body: unknown) {
    return this.request<T>(path, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  }

  delete<T>(path: string) {
    return this.request<T>(path, { method: 'DELETE' });
  }
}

export const apiClient = new ApiClient(API_BASE_URL);
export { API_BASE_URL };
