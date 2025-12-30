export type ApiError = {
  message: string
  status?: number
  url?: string
}

function joinUrl(base: string, path: string) {
  const normalizedBase = base.replace(/\/$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${normalizedBase}${normalizedPath}`
}

export async function apiGetJson<T>(path: string, options?: { signal?: AbortSignal }): Promise<T> {
  const base = import.meta.env.VITE_API_BASE_URL
  const url = joinUrl(base, path)

  let response: Response
  try {
    response = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
      signal: options?.signal,
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Network error'
    throw { message, url } satisfies ApiError
  }

  if (!response.ok) {
    let bodyText: string | undefined
    try {
      bodyText = await response.text()
    } catch {
      bodyText = undefined
    }
    throw {
      message: bodyText?.trim() || `Request failed (${response.status})`,
      status: response.status,
      url,
    } satisfies ApiError
  }

  return (await response.json()) as T
}
