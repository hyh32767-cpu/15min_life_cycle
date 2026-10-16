import { afterEach, describe, expect, it, vi } from 'vitest'
import { LiveApiProvider } from '@/providers/live'
import { ApiError } from '@/providers/errors'

afterEach(() => vi.unstubAllGlobals())
describe('typed API errors', () => {
  it('preserves quota and cooldown metadata without automatically retrying or exposing raw upstream text', async () => {
    const fetch = vi.fn(async () => ({ ok: false, status: 429, text: async () => JSON.stringify({ error: {
      code: 'QUOTA_EXCEEDED', message: 'https://upstream?secret=should-not-display', retryable: false, retryAfterSeconds: 3600,
    } }) }))
    vi.stubGlobal('fetch', fetch)
    const error = await new LiveApiProvider().getHealth().catch(error => error as ApiError)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'QUOTA_EXCEEDED', status: 429, retryable: false, retryAfterSeconds: 3600 })
    expect((error as ApiError).message).not.toContain('secret')
    expect(fetch).toHaveBeenCalledOnce()
  })
  it('distinguishes malformed HTTP responses from an empty search result', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, text: async () => '<html>proxy error</html>' })))
    await expect(new LiveApiProvider().getHealth()).rejects.toMatchObject({ code: 'INVALID_RESPONSE', retryable: true })
  })
})
