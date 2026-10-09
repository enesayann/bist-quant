export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");

export async function apiRequest(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<unknown> {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 30000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      credentials: "omit",
    });
    const payload: unknown = await response.json();
    if (!response.ok) {
      const error = (payload && typeof payload === "object" ? payload : {}) as {
        error?: { code?: string; message?: string };
      };
      throw new ApiError(
        error.error?.code || "api_error",
        error.error?.message || "Analysis failed. Try again later.",
      );
    }
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (timedOut)
      throw new ApiError(
        "request_timeout",
        "The analysis request timed out. Try again later.",
      );
    if (signal?.aborted)
      throw new DOMException("Analysis cancelled", "AbortError");
    if (error instanceof SyntaxError)
      throw new ApiError(
        "invalid_response",
        "The API returned an invalid response.",
      );
    throw new ApiError(
      "connection_error",
      "Cannot reach the API. Start the API on port 8000 or check its configured URL.",
    );
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

export const apiGet = (path: string, signal?: AbortSignal) =>
  apiRequest(path, undefined, signal);
