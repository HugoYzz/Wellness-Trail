import { expect, test } from '@playwright/test'

type SeenEvent = { id: number; event: string; data: Record<string, unknown> }

test('SSE 断线重连只落一组消息并从事件游标继续', async ({ page }) => {
  const setup = await page.request.post('/api/auth/setup', { data: { pin: '135790' } })
  expect(setup.ok()).toBeTruthy()
  await page.goto('/')

  const result = await page.evaluate(async () => {
    const requestId = `e2e-${Date.now()}`
    const body = JSON.stringify({ content: '请记录这条断线测试消息', request_id: requestId })

    async function readEvents(response: Response, stopAfterToken = false) {
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      const events: SeenEvent[] = []
      let buffer = ''
      for (;;) {
        const chunk = await reader.read()
        if (chunk.done) break
        buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replaceAll('\r\n', '\n')
        let boundary = buffer.indexOf('\n\n')
        while (boundary >= 0) {
          const block = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const id = Number(block.match(/^id: (\d+)$/m)?.[1] ?? 0)
          const event = block.match(/^event: (.+)$/m)?.[1] ?? ''
          const dataText = block.match(/^data: (.+)$/m)?.[1]
          if (id && event && dataText) events.push({ id, event, data: JSON.parse(dataText) })
          if (stopAfterToken && event === 'token') {
            await reader.cancel('simulate network disconnect')
            return events
          }
          boundary = buffer.indexOf('\n\n')
        }
      }
      return events
    }

    const firstResponse = await fetch('/api/chats/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body,
    })
    const chatId = Number(firstResponse.headers.get('X-Chat-Id'))
    const firstEvents = await readEvents(firstResponse, true)
    const lastEventId = Math.max(...firstEvents.map((event) => event.id))

    await new Promise((resolve) => setTimeout(resolve, 1_000))
    const resumedResponse = await fetch(`/api/chats/${chatId}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Last-Event-ID': String(lastEventId),
      },
      credentials: 'same-origin',
      body,
    })
    const resumedEvents = await readEvents(resumedResponse)
    return { chatId, firstEvents, resumedEvents, lastEventId }
  })

  expect(result.firstEvents.map((event) => event.event)).toContain('token')
  expect(result.resumedEvents.map((event) => event.event)).toContain('done')
  expect(result.resumedEvents.every((event) => event.id > result.lastEventId)).toBeTruthy()
  expect(result.resumedEvents.map((event) => event.event)).not.toContain('token')

  const messagesResponse = await page.request.get(`/api/chats/${result.chatId}/messages`)
  expect(messagesResponse.ok()).toBeTruthy()
  const messages = await messagesResponse.json()
  expect(messages.filter((message: { role: string }) => message.role === 'user')).toHaveLength(1)
  expect(messages.filter((message: { role: string }) => message.role === 'assistant')).toHaveLength(1)
})
