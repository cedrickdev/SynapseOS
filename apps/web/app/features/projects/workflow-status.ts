interface TerminalWorkflowProjection {
  readonly terminal: boolean
}

export function nextWorkflowPollDelay(
  status: TerminalWorkflowProjection | undefined,
): number | false {
  return status && !status.terminal ? 3_000 : false
}
