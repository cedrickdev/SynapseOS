export async function readBoundedRequestJson(
  stream: AsyncIterable<Uint8Array | string>,
  maxBytes: number,
): Promise<Record<string, unknown>> {
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) {
    throw new Error('invalid control request')
  }
  const chunks: Uint8Array[] = []
  let totalBytes = 0
  for await (const chunk of stream) {
    const bytes = typeof chunk === 'string' ? new TextEncoder().encode(chunk) : chunk
    totalBytes += bytes.byteLength
    if (totalBytes > maxBytes) {
      throw new Error('invalid control request')
    }
    chunks.push(bytes)
  }
  const content = new Uint8Array(totalBytes)
  let offset = 0
  for (const chunk of chunks) {
    content.set(chunk, offset)
    offset += chunk.byteLength
  }
  try {
    const value: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(content))
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      throw new Error
    }
    return value as Record<string, unknown>
  } catch {
    throw new Error('invalid control request')
  }
}
