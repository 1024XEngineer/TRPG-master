export interface ErrorDetail {
  code: string;
  message: string;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ErrorDetail | null;
}

export interface Example {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExampleCreateInput {
  name: string;
  description?: string | null;
}

export interface ExampleUpdateInput {
  name: string;
  description?: string | null;
}
