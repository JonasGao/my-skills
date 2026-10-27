# Keep Feishu Secrets in a Config File Outside Agent Reach

feishu-notify credentials (webhook URLs, signing secrets, bot keywords, app
secrets) live only in the user-level config file, written with owner-only
permissions and read exclusively by the skill's scripts. The skill ships no
field-level credential environment variables — the only override is the
config-path variable — and no environment-reference syntax inside the file.
Scripts mask every secret-bearing value in all output, tokens and signatures
exist only inside script memory, and SKILL.md carries a trust contract: the
Agent never reads the config, never passes secrets on a command line, and
when configuration is missing its entire job is to print the interactive
configure script's absolute path for the user to run in their own terminal.

## Status

Accepted

## Consequences

- Secrets can never leak through argv, stdout/stderr, stack traces, or the
  conversation; masking (last 4 characters or has-flags) is the only
  permitted display form.
- Injecting credentials via environment (the weekly-reporter pattern) is
  deliberately unavailable; a machine needing different credentials points
  the config-path variable at its own file.
- The config file is never committed to any repository.
- Interactive setup is human-terminal-only with masked input and no
  Agent-mediated entry, so credentials never transit an Agent transcript.
- Any future receive-mode (websocket) work must keep tokens inside script
  memory under the same contract.
