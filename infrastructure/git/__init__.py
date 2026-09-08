"""Local Git provider integrations."""

from infrastructure.git.local import LocalGitProvider
from infrastructure.git.policy import ObviousSecretCommitPolicy

__all__ = ["LocalGitProvider", "ObviousSecretCommitPolicy"]
