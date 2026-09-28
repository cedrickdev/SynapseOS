interface RequestAbortSource {
  readonly aborted: boolean
  once(event: 'aborted', listener: () => void): unknown
  off(event: 'aborted', listener: () => void): unknown
}

interface ResponseCloseSource {
  readonly writableEnded: boolean
  once(event: 'close', listener: () => void): unknown
  off(event: 'close', listener: () => void): unknown
}

export interface RequestCancellationScope {
  readonly signal: AbortSignal
  dispose(): void
}

export function createRequestCancellationScope(
  request: RequestAbortSource,
  response: ResponseCloseSource,
): RequestCancellationScope {
  const controller = new AbortController()
  const abort = () => controller.abort()
  const abortOnPrematureClose = () => {
    if (!response.writableEnded) {
      abort()
    }
  }
  request.once('aborted', abort)
  response.once('close', abortOnPrematureClose)
  if (request.aborted) {
    abort()
  }
  return {
    signal: controller.signal,
    dispose() {
      request.off('aborted', abort)
      response.off('close', abortOnPrematureClose)
    },
  }
}
