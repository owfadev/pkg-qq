# -*- coding: utf-8 -*-
"""qq-cli: a transport-only CLI for the official QQ Bot open platform.

Positioning (same split as the other owfa connectors): this package is a data
plane, not an agent. It authenticates, receives the official event stream,
normalizes and spools messages locally, enforces the local allowlist, and sends
passive replies. It never reads wiki content, never composes an answer, and
never runs an LLM. The agent session is the only answerer.

Credentials and raw message state live under ~/.qq-cli/ (0600) and never enter
the repository.
"""

__version__ = "0.2.0"
