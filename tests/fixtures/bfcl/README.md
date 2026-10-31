# BFCL v4 fixture subset

`bfcl_v4_subset.jsonl` holds 200 non-live cases from the Berkeley Function Calling
Leaderboard (BFCL) v4: 80 `simple_python`, 40 `multiple`, 40 `parallel`,
40 `parallel_multiple`. Each line merges the question file and its
`possible_answer` ground truth (`ground_truth` key). Cases were sampled with a fixed stride.

- Source: https://github.com/ShishirPatil/gorilla, `berkeley-function-call-leaderboard/bfcl_eval/data/`
  at commit 6ea57973c7a6097fd7c5915698c54c17c5b1b6c8.
- License: Apache-2.0, Copyright the Gorilla / BFCL authors (UC Berkeley). The full text is in
  `LICENSE.gorilla-apache-2.0`. Changes: subset selection and merging into one JSONL file.
- Citation: Patil et al., "The Berkeley Function Calling Leaderboard (BFCL): From Tool Use
  to Agentic Evaluation of Large Language Models", ICML 2025.

Regenerate or convert with `python3 scripts/bfcl_adapter.py --help`.
