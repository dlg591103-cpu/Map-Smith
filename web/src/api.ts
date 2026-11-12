import type { UploadInfo } from './types'

export class ApiError extends Error {}

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (body && typeof body.detail === 'string') return body.detail
    if (body && typeof body.message === 'string') return body.message
  } catch {
    // 非 JSON 错误体，回退到文本
  }
  const text = await response.text().catch(() => '')
  return text || `请求失败（HTTP ${response.status}）`
}

export async function streamPost(
  url: string,
  body: unknown,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): Promise<void> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new ApiError(await readError(response))
  if (!response.body) throw new ApiError('服务没有返回流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let index = buffer.indexOf('\n\n')
    while (index >= 0) {
      const block = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      let event = 'message'
      let data = '{}'
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data = line.slice(5).trim()
      }
      try {
        onEvent(event, JSON.parse(data) as Record<string, unknown>)
      } catch {
        // 忽略无法解析的片段，不让整个流中断
      }
      index = buffer.indexOf('\n\n')
    }
  }
}

export async function uploadFile(file: File): Promise<UploadInfo> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch('/api/upload', { method: 'POST', body: form })
  if (!response.ok) throw new ApiError(await readError(response))
  return (await response.json()) as UploadInfo
}

export async function confirmCrs(uploadId: string, crs: string): Promise<UploadInfo> {
  const response = await fetch(`/api/upload/${uploadId}/crs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ crs }),
  })
  if (!response.ok) throw new ApiError(await readError(response))
  return (await response.json()) as UploadInfo
}

export async function health(): Promise<{ status: string; llm_configured: boolean; version: string }> {
  const response = await fetch('/api/health')
  if (!response.ok) throw new ApiError(await readError(response))
  return (await response.json()) as { status: string; llm_configured: boolean; version: string }
}