<!-- DRAFT — not published. Placeholders (<VERSION>, <DATE>, <RELEASE_URL>) must be filled and every item confirmed merged before release. -->

# X thread draft: familia <VERSION>

<!-- Placeholders: <VERSION>, <RELEASE_URL>. Character counts are checked by ../check_x_thread.py (limit 280; URLs count as 23 on X). -->

**1/**
familia <VERSION> is out: the first real release.

It ties together the local AI I already run (llama.cpp servers, a model alias gateway, an agent fleet, hermes-agent) across my own machines, as one graph I control.

<RELEASE_URL>

**2/**
The one rule: your models and data stay on your machines. A file, context, or result crosses a boundary only when you say so.

You own every edge. familia may suggest a connection. It never opens one on its own.

**3/**
Two clicks to install:

curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh | sh

then type "yes" to a voluntary contribution notice. Paying is never required.

**4/**
In this release: the rename from its sketch name is finished, Android/Termux keeps the server alive in the background, experimental llama.cpp forks can sit beside the default build, and the docs now match the code.

**5/**
Next: configuration you declare, not configuration that guesses.

Declare your models and agents. familia checks them against your measured hardware. No silent model swaps, no inflated context. A mismatch fails loudly.

**6/**
The design is still a draft and feedback is welcome:
https://github.com/brianreborn/familia/blob/main/docs/configuration-graph.md

Light-ware licensed (BSD-4 plus an invitation, not a condition).
