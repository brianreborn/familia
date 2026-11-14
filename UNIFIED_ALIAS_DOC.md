================================================================================
FAMILIA ALIAS & ROUTE DOCUMENTATION (Offline Copy)
================================================================================

VERSION: 0.3.0-fix
PURPOSE: Documents all alias mappings, route names, and hermes configuration
         so users understand the routing system without needing network access.
================================================================================

1. ROUTE NAME RULE (DESIGN.md)
   ---------------------------
   "A name a person or an agent types is one English word for the job."
   `coder` stays. No vendor, no parameter count, no `-agent`, no `-speculator`.
   The directory `models/<name>/` is that same word.
   A GGUF filename and a draft model are not route names.

2. ROUTE COLUMN TABLE (DESIGN.md:45-70)
   -------------------------------------
   The official route mapping every agent type → route name:

   | Agent Type                | Route Name |
   |---------------------------|------------|
   | general, general-text-speculator | `chat`    |
   | coder, qwenstral-code-speculator | `coder`   |
   | decision, tool-router-agent  | `route`   |
   | language                  | `translate`|
   | vision-layout-agent       | `vision`   |
   | audio-transcription-agent | `transcribe`|
   | speech-synthesis-agent    | `speak`    |
   | image-generation-agent    | `draw`     |
   | semantic-embedding-agent  | `embed`    |
   | retrieval-rerank-agent    | `rerank`   |
   | safety-policy-agent       | `safety`   |
   | security-monitor-agent    | `guard`    |

3. ALIAS MAPPINGS (graph.yaml)
   ---------------------------
   The graph.yaml aliases system maps named nodes to their configurations.
   Key aliases from current graph.yaml:

   | Alias     | Maps To        | Gateway  |
   |-----------|----------------|----------|
   | `coder`   | node: coder    | roomz    |
   | `general` | node: coder    | roomz    |
   | `embed`   | node: embed    | roomz    |
   | `guardian`| node: miryam-pentest | roomz |
   | `pentest` | node: miryam-pentest | roomz  |
   | `defender`| node: miryam-pentest | roomz  |

   NOTE: `general` alias maps to the `coder` node — this is intentional.
   The `general` section name is different from the `general` route name.

4. SLASH COMMANDS & THEIR ROUTES
   -------------------------------
   These slash commands ALL route to the same place (chat/default):

   | Slash Command | Routes To          | Via                    |
   |---------------|-------------------|------------------------|
   | `/chat`       | chat default      | graph.yaml alias + hermes.sh |
   | `/text`       | chat default      | graph.yaml alias + hermes.sh |
   | `/general`    | chat default      | graph.yaml alias + hermes.sh |
   | `/general-text-speculator` | chat default | graph.yaml alias + hermes.sh |

   WHY THEY'RE THE SAME:
   - DESIGN.md: "general, general-text-speculator → `chat`"
   - The launcher opens `chat` first
   - `coder` is a handoff from `chat` or `route`, not the front door
   - All three are English-word route names per the route name rule

5. HERMES-CONFIGURATION FROM THE START
   -----------------------------------
   Use the familia program to establish proper configuration:

   $ ./familia first-time --yes
   → deps → licenses → configure → install → PATH

   This handles the FULL checklist in order:
   1. Dependencies (FreeBSD packages, etc.)
   2. License acceptance (scripts/licenses.py review --yes)
   3. Configuration (scripts/configure.sh --interactive)
   4. Install (install/freebsd/install-familia.sh or ./familia first-time)
   5. PATH setup (familia on PATH or ./familia)

   ALTERNATIVE: Single-command setup
   $ ./familia first-time --yes --dry-run  # Preview only
   $ ./familia first-time --yes           # Actual install

6. PROPER HERMES CONFIGURATION FLOW
   ----------------------------------
   Step 1: Install familia
   $ ./familia first-time --yes

   Step 2: Start the graph
   $ ./start.sh --host angel

   Step 3: Launch hermes in desired mode
   
   # Graph mode (default — uses aliases from graph.yaml)
   $ ./scripts/hermes.sh --mode graph --model coder
   
   # Single-model mode (one node, own HERMES_HOME)
   $ ./scripts/hermes.sh --model coder
   
   # With desktop frontend
   $ ./scripts/hermes.sh --model coder --client desktop --yes
   
   # With webapp frontend
   $ ./scripts/hermes.sh --model coder --client webapp --yes

   Step 4: Use slash commands (when llama-server is running)
   
   # Via web UI (unicorn.html):
   # Type: /chat, /text, /general — all go to chat default
   
   # Via direct POST:
   $ curl -X POST http://127.0.0.1:18080/v1/chat/completions        -H "Content-Type: application/json"        -d '{"model": "coder", "messages": [{"role": "user", "content": "hello"}]}'

7. ALIAS QUICK REFERENCE CARD
   ---------------------------
   Print this and keep it handy:

   ROUTE NAMES (one English word):
   •  chat    → general conversation (DEFAULT)
   •  coder   → code assistance
   •  translate → language translation
   •  vision   → image/layout analysis
   •  embed    → semantic embedding
   •  rerank   → retrieval reranking
   •  safety   → safety policy checks
   •  guard    → security monitoring

   SLASH COMMANDS (all chat/default):
   •  /chat     → chat default
   •  /text     → chat default 
   •  /general  → chat default
   •  /auto     → auto-complete
   •  /vision   → vision tasks

   HERMES LAUNCH COMMANDS:
   •  ./scripts/hermes.sh --mode graph --model NODE
   •  ./scripts/hermes.sh --model NODE
   •  ./scripts/hermes.sh --mode single --model NODE
   •  ./scripts/hermes.sh --model NODE --client desktop --yes
   •  ./scripts/hermes.sh --model NODE --client webapp --yes

8. OFF-LINE ACCESS
   ----------------
   This documentation is self-contained — no network required.
   Copy to: ~/.hermes/aliases-doc.md or keep in ~/.hermes/cache/scratch/
   Also available via: sh scripts/open_ui.sh → help section

   To generate fresh copy:
   $ cp docs/alias-documentation.md ~/.hermes/aliases-doc.md
   Or: $ python3 -c "
   with open('aliases-doc.md', 'w') as f:
       f.write(open('UNIFIED_ALIAS_DOC.md').read())
   "

================================================================================
