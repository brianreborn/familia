# RouterBench synthetic fixture

`synthetic_wide.jsonl` is hand-made, NOT RouterBench data. It mimics the RouterBench
wide layout (`sample_id`, `eval_name`, `prompt`, per-model score column `M`,
`M|total_cost`, `M|model_response`) with 3 made-up models and 6 prompts so the scorer's
numbers can be checked by hand. Real data is never committed; load it from a local path
with `--data` or `ROUTERBENCH_DATA` (see `scripts/routerbench_scorer.py`).
