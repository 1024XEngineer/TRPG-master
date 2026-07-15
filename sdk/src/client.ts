import type { ApiResponse } from './types';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  fetch?: typeof fetch;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
  }

  async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...init?.headers
      }
    });

    const body = (await response.json()) as ApiResponse<T>;

    if (!body.success || body.error) {
      throw new ApiError(
        body.error?.code ?? 'UNKNOWN_ERROR',
        body.error?.message ?? '请求失败',
        response.status
      );
    }

    return body.data as T;
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: 'GET' });
  }

  post<T>(path: string, payload: unknown): Promise<T> {
    return this.request<T>(path, { method: 'POST', body: JSON.stringify(payload) });
  }

  put<T>(path: string, payload: unknown): Promise<T> {
    return this.request<T>(path, { method: 'PUT', body: JSON.stringify(payload) });
  }

  delete<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: 'DELETE' });
  }
}
