import { EventEmitter } from 'node:events'

import { describe, expect, it } from 'vitest'

import { createRequestCancellationScope } from '../../server/utils/request-cancellation'

class RequestSource extends EventEmitter {
  aborted = false
}

class ResponseSource extends EventEmitter {
  writableEnded = false
}

describe('request cancellation scope', () => {
  it('aborts outbound work when the client connection closes', () => {
    const request = new RequestSource()
    const response = new ResponseSource()
    const scope = createRequestCancellationScope(request, response)

    response.emit('close')

    expect(scope.signal.aborted).toBe(true)
    scope.dispose()
  })

  it('removes listeners when outbound work completes', () => {
    const request = new RequestSource()
    const response = new ResponseSource()
    const scope = createRequestCancellationScope(request, response)

    scope.dispose()
    request.emit('aborted')
    response.emit('close')

    expect(scope.signal.aborted).toBe(false)
  })
})
