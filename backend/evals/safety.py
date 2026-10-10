"""Shared safety preamble for bounded external-repository evaluations."""

PREAMBLE = (
    "Work only within this attempt's disposable worktree. Do not read other repositories, "
    "sibling directories, evaluation data, held-out verifiers, or home-directory user data. "
    "Do not fetch upstream solutions, use network services, or delegate to other agents. "
    "Follow repository AGENTS.md safety instructions. Dependencies are already installed. "
    "Use focused local checks, not repository-wide checks or browsers. "
    "Only production source changes necessary for the current task may remain changed. "
    "Do not modify tooling, dependencies, instructions, or existing test files. "
    "Held-out tests are intentionally absent and will be installed after the run; "
    "do not recreate their paths. Scratch files must not remain in the scored diff."
)
