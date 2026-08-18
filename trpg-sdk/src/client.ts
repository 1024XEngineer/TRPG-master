import type { ApiResponse } from './types';

/**
 * 后端返回 `{ success: false, error: {...} }` 时，统一转成这个异常抛出，
 * 而不是让调用方每次都手动检查 `response.success`——用 try/catch 处理错误
 * 更符合 JS/TS 里常见的错误处理习惯，也方便和网络层面的异常（比如断网）
 * 用同一套 catch 逻辑处理。
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  /**
   * 后端 `AppException.details` 的原样透传。
   *
   * 有些错误码光靠 message 用不起来：比如 `CHARACTER_TEMPLATE_DUPLICATE` 会带上
   * 卡库里既有那张卡的 `templateId`，调用方要据此把界面指向它，而不是丢一句
   * "保存失败"。
   */
  readonly details: Array<Record<string, string>> | null;

  constructor(
    code: string,
    message: string,
    status: number,
    details: Array<Record<string, string>> | null = null
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export interface ApiClientOptions {
  /** 后端 API 的根地址，比如 "http://127.0.0.1:8000/api/v1"（要包含版本前缀）。 */
  baseUrl: string;
  /** 自定义 fetch 实现，主要给 Node 环境或单元测试注入 mock 用；不传就用全局 fetch。 */
  fetch?: typeof fetch;
}

/**
 * 最底层的 HTTP 封装：拼 URL、加公共 header、解析统一响应信封、
 * 把 `success:false` 转成 ApiError。上层的 `resources/*`（比如 AuthResource）
 * 都是基于这个类的 get/post/put/delete 方法实现的，不直接碰 fetch。
 */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions) {
    // 去掉末尾的斜杠，避免使用方传了 "http://host/" 导致后面拼接时出现 "//"。
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    // 注意这里必须 `.bind(globalThis)`：如果直接写 `options.fetch ?? fetch`，
    // 拿到的是一个和 `window`/`globalThis` 解绑的裸函数引用，之后用
    // `this.fetchImpl(...)` 的方式调用会报 `Illegal invocation`
    // ——浏览器原生 fetch 的实现依赖调用时的 this 是 window，这是我们在
    // 真机联调时踩到的一个真实 bug，这里的注释就是防止以后又被坑一次。
    this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
  }

  /**
   * 发起一次请求并按统一响应信封解析结果。
   * 成功时直接返回 `data` 字段（调用方不需要自己拆 `{success,data,error}`）；
   * 失败（`success:false`）或网络异常都会以抛异常的形式表现。
   */
  async request<T>(path: string, init?: RequestInit): Promise<T> {
    // `HeadersInit` 有三种形态：Headers 实例 / string[][] / Record<string,string>。
    // 之前这里写的 `{...init?.headers}` 只对 Record<string,string> 是对的——
    // 展开 Headers 实例得到 `{}`（它没有可枚举自有属性），展开 string[][]
    // 得到 `{0:[...],1:[...]}`，两种情况下调用方传的 header 都会静默失效、
    // 不报错（issue #75 code review 时发现的真实 bug，见 client.test.ts）。
    // `new Headers(...)` 本身就能正确解析这三种形态，这里委托给它，而不是
    // 自己再判断一次调用方传的是哪种形态。
    const headers = new Headers({ 'Content-Type': 'application/json' });
    if (init?.headers) {
      new Headers(init.headers).forEach((value, key) => headers.set(key, value));
    }

    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers
    });

    const body = (await response.json()) as ApiResponse<T>;

    if (!body.success || body.error) {
      throw new ApiError(
        body.error?.code ?? 'UNKNOWN_ERROR',
        body.error?.message ?? '请求失败',
        response.status,
        body.error?.details ?? null
      );
    }

    return body.data as T;
  }

  /** 成功响应按 Blob 返回；错误响应仍解析统一 JSON 信封。 */
  async requestBlob(path: string, init?: RequestInit): Promise<Blob> {
    const headers = new Headers(init?.headers);
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers
    });
    if (!response.ok) {
      // 音频接口只有成功分支是二进制；失败仍遵守全站 JSON 错误信封。先按状态码
      // 分流，避免把一段错误 JSON 当成 MP3 交给 HTMLAudioElement。
      let body: ApiResponse<unknown> | null = null;
      try {
        body = (await response.json()) as ApiResponse<unknown>;
      } catch {
        // 非标准上游错误也收敛为稳定 SDK 异常，不向调用方暴露解析细节。
      }
      throw new ApiError(
        body?.error?.code ?? 'UNKNOWN_ERROR',
        body?.error?.message ?? '请求失败',
        response.status,
        body?.error?.details ?? null
      );
    }
    return response.blob();
  }

  get<T>(path: string, init?: RequestInit): Promise<T> {
    return this.request<T>(path, { ...init, method: 'GET' });
  }

  post<T>(path: string, payload: unknown, init?: RequestInit): Promise<T> {
    return this.request<T>(path, {
      ...init,
      method: 'POST',
      body: JSON.stringify(payload)
    });
  }

  put<T>(path: string, payload: unknown): Promise<T> {
    return this.request<T>(path, { method: 'PUT', body: JSON.stringify(payload) });
  }

  patch<T>(path: string, payload: unknown, init?: RequestInit): Promise<T> {
    return this.request<T>(path, {
      ...init,
      method: 'PATCH',
      body: JSON.stringify(payload)
    });
  }

  delete<T>(path: string, init?: RequestInit): Promise<T> {
    return this.request<T>(path, { ...init, method: 'DELETE' });
  }
}
