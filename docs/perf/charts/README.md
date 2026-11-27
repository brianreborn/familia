# Measured performance charts

`recent-measured-performance.svg` is generated from
`docs/perf/valid-2026-10-27/fleet-perf-summary.json` by:

```sh
python3 scripts/perf/plot_recent_performance.py
```

The left panel is a same-host SmolLM2 CPU thread sweep on Miryam. The right
panel places the committed phone8 Vulkan anchor beside Miryam CPU anchors for
scale only; those runs use different hardware and prompt lengths and are not a
causal comparison.

No chart here attributes a speedup to the MLC schema work or HVVRAM work. Those
features need fresh, paired measurements before they can be shown as gains.
