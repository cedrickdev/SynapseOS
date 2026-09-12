const JSON_CONTENT_TYPES = ['application/json', 'application/problem+json']

export class BackendResponseError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'BackendResponseError'
  }
}

function isJsonContentType(contentType: string): boolean {
  return JSON_CONTENT_TYPES.some(type => contentType.toLocaleLowerCase('en-US').includes(type))
}

export async function readBoundedJson(response: Response, maxBytes: number): Promise<unknown> {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) {
    throw new BackendResponseError('invalid response size limit')
  }

  const contentType = response.headers.get('content-type') ?? ''
  if (!isJsonContentType(contentType)) {
    throw new BackendResponseError('backend returned an unsupported content type')
  }

  const declaredLength = Number(response.headers.get('content-length'))
  if (Number.isFinite(declaredLength) && declaredLength > maxBytes) {
    throw new BackendResponseError('backend response exceeded the configured limit')
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new BackendResponseError('backend returned an empty response body')
  }

  const chunks: Uint8Array[] = []
  let receivedBytes = 0
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    receivedBytes += value.byteLength
    if (receivedBytes > maxBytes) {
      await reader.cancel()
      throw new BackendResponseError('backend response exceeded the configured limit')
    }
    chunks.push(value)
  }

  const bytes = new Uint8Array(receivedBytes)
  let offset = 0
  for (const chunk of chunks) {
    bytes.set(chunk, offset)
    offset += chunk.byteLength
  }

  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as unknown
  } catch {
    throw new BackendResponseError('backend returned invalid JSON')
  }
}
