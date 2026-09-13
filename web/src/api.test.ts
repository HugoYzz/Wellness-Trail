import { describe, expect, it, vi } from 'vitest'

import { sendMessageStream } from './api'

function sseResponse(body: string, chatId: number): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', 'X-Chat-Id': String(chatId) },
  })
}

describe('sendMessageStream', () => {
  it('断线后复用 request_id 并从 Last-Event-ID 继续且不重复 token', async () => {
    const requests: Array<{ url: string; init: RequestInit }> = []
    const responses = [
      sseResponse(
        'id: 1\nevent: meta\ndata: {"chat_id":42,"request_id":"server-id"}\n\n'
          + 'id: 2\nevent: token\ndata: {"text":"收到"}\n\n',
        42,
      ),
      sseResponse(
        'id: 2\nevent: token\ndata: {"text":"收到"}\n\n'
          + 'id: 3\nevent: done\ndata: {"usage":{"total_tokens":9},"message_id":7,"error":null}\n\n',
        42,
      ),
    ]
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      requests.push({ url, init })
      const response = responses.shift()
      if (!response) throw new Error('unexpected fetch')
      return response
    }))

    const tokens: string[] = []
    const retries: number[] = []
    const done = vi.fn()
    const chatId = await sendMessageStream(null, '测试断线续传', {
      onToken: (token) => tokens.push(token),
      onCard: vi.fn(),
      onDone: done,
      onRetry: (attempt) => retries.push(attempt),
    })

    expect(chatId).toBe(42)
    expect(tokens).toEqual(['收到'])
    expect(retries).toEqual([1])
    expect(done).toHaveBeenCalledOnce()
    expect(requests.map((request) => request.url)).toEqual([
      '/api/chats/messages',
      '/api/chats/42/messages',
    ])
    expect((requests[1].init.headers as Record<string, string>)['Last-Event-ID']).toBe('2')
    const firstBody = JSON.parse(String(requests[0].init.body))
    const secondBody = JSON.parse(String(requests[1].init.body))
    expect(firstBody.request_id).toBe(secondBody.request_id)
    expect(firstBody.content).toBe('测试断线续传')
  })
})
