# HVVRAM sparse-gather experiment

This is the next research iteration for [#298](https://github.com/brianreborn/familia/issues/298).
It measures the narrow claim that a large, read-only sparse table can stay
file-backed while each operation fetches only a few fixed-size rows.

The benchmark compares three explicit arms:

- `mmap`: file-backed reads, with `madvise(MADV_RANDOM)` or sequential advice;
- `pread`: direct row reads without a persistent mapping;
- `load`: a full-resident baseline.

Each arm uses the same deterministic row sequence and reports p50/p99/max
gather latency, RSS before/after, and resident file pages when `mincore` is
available. A digest makes it difficult for an arm to pass without consuming
the row bytes.

## Safe runs

The default creates a 16 MiB table and does not touch global page-cache state:

```sh
python3 scripts/perf/hvvram_sparse_gather.py \
  --file /tmp/hvvram-table.bin --output /tmp/hvvram.json
```

For a table larger than RAM, increase the size and quota explicitly. A cold
run creates and flushes the table first, then requires an operator-provided
cache-drop command before *each* arm; the script will not
write `/proc/sys/vm/drop_caches`, FreeBSD sysctls, or any other global control
interface implicitly:

```sh
python3 scripts/perf/hvvram_sparse_gather.py \
  --file /path/on/benchmark-volume/table.bin --rows 2097152 \
  --row-bytes 4096 --cache cold \
  --drop-cache-command 'sudo sh -c "sync; echo 3 > /proc/sys/vm/drop_caches"'
```

Cold and warm results must be kept as separate records. The experiment is
research-only and does not change graph admission or release gates.

## Reboot-comparable records and decision rule

Every report records the OS, machine architecture, kernel release, boot
identity when available, backing-file device, filesystem block size, and free
space. Keep the result JSON with the exact command and timestamp in the
operator ledger. A new boot is a new comparison group; do not pool its latency
percentiles with an earlier boot.

Before calling a run promising, apply the existing issue #298 thresholds to
the same table, row pattern, and host:

- cold `mmap` p99 must be no more than twice warm `mmap` p99; and
- `mmap` peak process RSS must remain below 10 percent of table size.

The report measures process RSS, not global page cache. Treat an unavailable
resident-page count as an observation gap, not as evidence that file pages
were absent.
