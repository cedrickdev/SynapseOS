# Managed project workspaces

Phase 9 gives each project one isolated local workspace controlled by SynapseOS. The implementation
is intentionally a local backend behind the provider-neutral `WorkspaceManager` contract; it does
not start execution containers, run shell commands, or add write tools.

## Lifecycle

`LocalWorkspaceManager` supports five audited operations:

- create an empty workspace;
- import the committed snapshot of an approved local Git repository;
- clone an approved credential-free HTTPS repository;
- validate a relative path inside the exact project root;
- clean up the exact project root.

Final roots are deterministic: `<base>/projects/<project_uuid>`. Population occurs in a private
staging directory and is promoted atomically. Cleanup first moves the root to private trash and
then removes it without following symbolic links. Per-project lock directories prevent concurrent
lifecycle changes.

Every terminal lifecycle result is appended to PostgreSQL as `WORKSPACE_LIFECYCLE`. A successful
workspace is not returned if its audit record cannot be written. Failed provisioning is
compensated, including trees that exceed normal workspace limits; compensation has separate finite
hard ceilings.

## Trust boundary

- A runtime `Workspace` is immutable and its root must be a canonical direct child derived from its
  project UUID.
- Relative paths are resolved through the existing non-following Phase 6 path guard.
- Local repositories are copied, never adopted in place, and must be below an explicit canonical
  allowlisted root.
- Remote clones accept only credential-free HTTPS URLs whose normalized host is exactly allowlisted.
- Git runs once without a shell, prompts, hooks, submodules, implicit retries, or inherited secrets.
- Git timeout, output, workspace entries, bytes, depth, local roots, and remote hosts are bounded.
- Cancellation terminates the child process, compensates staging, records `CANCELLED`, and is
  propagated to the caller.
- Errors and audit metadata contain stable classifications and allowlisted counters only; repository
  URLs, filesystem paths, process output, credentials, prompts, and file content are not persisted.

The default local and remote allowlists are empty, so repository imports are denied until explicitly
configured. This is application-level isolation, not an operating-system sandbox. A Docker or other
execution backend can implement the same contract in a later phase.

## Configuration

The settings are environment-driven:

| Variable | Default | Purpose |
| --- | --- | --- |
| `WORKSPACE_BASE_ROOT` | `.synapseos/workspaces` | Private manager-owned base |
| `WORKSPACE_GIT_TIMEOUT_SECONDS` | `120` | Hard Git process timeout |
| `WORKSPACE_GIT_OUTPUT_BYTES` | `65536` | Combined stdout/stderr byte limit |
| `WORKSPACE_MAX_ENTRIES` | `100000` | Maximum files/directories/links |
| `WORKSPACE_MAX_TOTAL_BYTES` | `1073741824` | Maximum regular-file bytes |
| `WORKSPACE_MAX_DEPTH` | `64` | Maximum tree depth |
| `WORKSPACE_LOCAL_IMPORT_ROOTS` | `[]` | JSON array of trusted local roots |
| `WORKSPACE_REMOTE_HOSTS` | `[]` | JSON array of trusted HTTPS hosts |

The base must be private and writable by the service account. Never place secrets in these settings
or inside repository URLs. The generated `.synapseos/` runtime directory is ignored by Git.

## Deliberate exclusions

Phase 9 adds no workspace database table or migration, write tool, arbitrary command execution,
sudo access, host-wide filesystem access, Docker execution backend, RLS, or cross-host workspace
coordination. Those concerns remain assigned to later roadmap phases.
