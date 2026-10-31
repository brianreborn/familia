#!/bin/sh
# hvvram-p0-zfs-baseline.sh — HVVRAM P0: wipe the Vertex 2 swap SSD (by serial ONLY),
# build the tuned "hvv" pool, run a bounded benchmark. Per HVVRAM-DESIGN-REVIEW.md §5.0.
# DRAFT — NOT RUN. Needs Brian's explicit approval before it is run as root on angel.
# Default is DRY RUN. Real run:  sh hvvram-p0-zfs-baseline.sh --apply
# Rollback:                      sh hvvram-p0-zfs-baseline.sh --rollback --apply
#
# Swap layout (Brian 2026-10-31): swap moves to its own encrypted zvol hvv/swap in this pool.
# The HDD partition ada0s1b is used only as a GELI-onetime bridge swap while ada1 (the old
# swap) is wiped; it is turned off once zvol swap is active, and its fstab line stays commented.
# Persistent zvol swap (fstab/rc) is NOT set here; it needs separate approval. Suggested line:
#   zfs set org.freebsd:swap=on hvv/swap   # or fstab: /dev/zvol/hvv/swap none swap sw,late 0 0
#   (the zvol key is ephemeral, so boot needs a keyed create step; see §5.0)
# Signed: Other Grok Bot ASSIST
set -eu

ALLOW_SERIAL="__VERTEX2_SERIAL__"     # real value kept only in familia-private
ALLOW_MODEL="OCZ-VERTEX2"
POOL=hvv
OUT=/var/tmp/hvvram-p0-$(date +%Y%m%dT%H%M%S%z)
ARC_MAX=$((2*1024*1024*1024)); ARC_MIN=$((512*1024*1024))
SWAP_SIZE=16G; BRIDGE=ada0s1b; BRIDGE_SERIAL="__HDD_SERIAL__"
BENCH_SIZE=4g; BENCH_TIME=60            # bounded: ~4 GiB per job, 60 s cap
APPLY=0; MODE=build
for a in "$@"; do case $a in --apply) APPLY=1;; --rollback) MODE=rollback;; *) echo "unknown arg $a"; exit 2;; esac; done

die(){ echo "ABORT: $*" >&2; exit 1; }
run(){ echo "+ $*"; if [ $APPLY -eq 1 ]; then "$@"; fi; }
[ "$(id -u)" -eq 0 ] || [ $APPLY -eq 0 ] || die "must be root for --apply"
mkdir -p "$OUT"   # tip: pipe through `tee $OUT/run.log`
echo "mode=$MODE apply=$APPLY out=$OUT"
case "$ALLOW_SERIAL$BRIDGE_SERIAL" in *__*) die "serial placeholder present; use the familia-private copy";; esac

# --- resolve the disk by serial (never by adaN) ---
DEV=""
for d in $(sysctl -n kern.disks); do
  ident=$(geom disk list "$d" | awk '/ident:/{print $2}')
  descr=$(geom disk list "$d" | sed -n 's/^ *descr: //p')
  [ "$ident" = "$ALLOW_SERIAL" ] && { [ "$descr" = "$ALLOW_MODEL" ] || die "$d serial matches but model '$descr'"; DEV=$d; }
done
[ -n "$DEV" ] || die "no disk with serial $ALLOW_SERIAL present"
echo "target: /dev/$DEV ($ALLOW_MODEL $ALLOW_SERIAL)"

# --- refusals ---
ROOTDEV=$(mount -p | awk '$2=="/"{print $1}')
echo "$ROOTDEV" | grep -q "$DEV" && die "$DEV is the root/boot disk"
mount -p | awk '{print $1}' | grep -q "/dev/$DEV" && die "$DEV has mounted filesystems"
kldload -n zfs 2>/dev/null || [ $APPLY -eq 0 ] || die "cannot load zfs"
if kldstat -q -m zfs; then zpool status 2>/dev/null | grep -qw "$DEV" && [ $MODE = build ] && die "$DEV already in a pool"; fi
OTHERPARTS=$(gpart show "$DEV" 2>/dev/null | grep -v -e 'hvv0' -e '^$' -e '=>' -e 'free' || true)
[ $MODE = build ] && [ -n "$OTHERPARTS" ] && die "unexpected partitions on $DEV: $OTHERPARTS"

if [ $MODE = rollback ]; then
  echo "== ROLLBACK: destroy pool, restore fstab, re-enable swap on $DEV =="
  if [ $APPLY -eq 1 ]; then printf 'Type ROLLBACK %s: ' "$ALLOW_SERIAL"; read r; [ "$r" = "ROLLBACK $ALLOW_SERIAL" ] || die "not confirmed"; fi
  swapinfo | grep -q "zvol/$POOL/swap" && run swapoff "/dev/zvol/$POOL/swap"
  zpool list "$POOL" >/dev/null 2>&1 && run zpool destroy "$POOL"
  run gpart destroy -F "$DEV"
  B=$(ls -t /etc/fstab.hvvram-p0.* 2>/dev/null | head -1); [ -n "$B" ] && run cp -p "$B" /etc/fstab
  run sysctl vfs.zfs.arc.max=0 vfs.zfs.arc.min=0     # 0 = back to auto
  swapinfo | grep -q "/dev/$BRIDGE.eli" && run swapoff "/dev/$BRIDGE.eli"
  run swapon "/dev/$DEV"; swapinfo -h; exit 0
fi

# --- verify tunables exist on this FreeBSD (fail on unknown) ---
if kldstat -q -m zfs; then
  for t in vfs.zfs.arc.max vfs.zfs.arc.min; do sysctl -d "$t" >/dev/null 2>&1 || die "unknown tunable $t"; done
fi
command -v fio >/dev/null && BENCH=fio || BENCH=dd; echo "bench tool: $BENCH (nothing installed)"

# --- archive state before ---
{ freebsd-version -ku; geom disk list "$DEV"; camcontrol identify "$DEV" 2>&1; swapinfo; cat /etc/fstab; } > "$OUT/before.txt" 2>&1
command -v smartctl >/dev/null && smartctl -a "/dev/$DEV" > "$OUT/smart-before.txt" 2>&1 || echo "smartctl absent (not installing)"
sysctl -a > "$OUT/sysctl-before.txt" 2>/dev/null

# --- typed confirmation ---
if [ $APPLY -eq 1 ]; then
  printf 'This ERASES %s (%s). Type WIPE %s: ' "/dev/$DEV" "$ALLOW_MODEL" "$ALLOW_SERIAL"; read reply
  [ "$reply" = "WIPE $ALLOW_SERIAL" ] || die "not confirmed"
fi

# --- bridge swap on HDD (GELI onetime) so there is no no-swap window; abort before touching $DEV ---
BD=${BRIDGE%%s*}
[ "$(geom disk list "$BD" | awk '/ident:/{print $2}')" = "$BRIDGE_SERIAL" ] || die "bridge disk $BD serial mismatch"
[ -c "/dev/$BRIDGE" ] || die "/dev/$BRIDGE missing"
gpart show "$BD" | grep -q "freebsd-swap" || die "no freebsd-swap partition on $BD"
mount -p | awk '{print $1}' | grep -q "/dev/$BRIDGE" && die "$BRIDGE is mounted"
if [ $APPLY -eq 1 ]; then
  [ -c "/dev/$BRIDGE.eli" ] || geli onetime -e AES-XTS -l 256 -d "$BRIDGE" || die "geli onetime failed; $DEV untouched"
  swapon "/dev/$BRIDGE.eli" || die "bridge swapon failed; $DEV untouched"
  swapinfo | grep -q "$BRIDGE.eli" || die "bridge swap not active; $DEV untouched"
else echo "+ geli onetime -d $BRIDGE && swapon /dev/$BRIDGE.eli"; fi

# --- swap off + fstab (backup first) ---
swapinfo | grep -q "/dev/$DEV" && run swapoff "/dev/$DEV"
run cp -p /etc/fstab "/etc/fstab.hvvram-p0.$(date +%Y%m%d%H%M%S)"
[ $APPLY -eq 1 ] && sed -i '' "s|^/dev/$DEV[[:space:]].*swap.*|#&  # disabled by hvvram-p0|" /etc/fstab

# --- partition + pool (GPT label, never adaN) ---
run gpart create -s gpt "$DEV"
run gpart add -t freebsd-zfs -a 1m -l hvv0 "$DEV"
run zpool create -o ashift=12 -o autotrim=on -O atime=off -O xattr=sa -O compression=lz4 \
    -O checksum=fletcher4 -O redundant_metadata=most -O exec=off -O setuid=off -O devices=off \
    "$POOL" /dev/gpt/hvv0
run zfs create -o recordsize=1M -o compression=off -o primarycache=metadata -o secondarycache=none "$POOL/weights"
EK="-o encryption=aes-256-gcm -o keyformat=raw -o keylocation=prompt"
for ds in kv:64K spill:1M; do n=${ds%%:*}; rs=${ds#*:}
  echo "+ ephemeral key -> zfs create $POOL/$n (key never written to disk)"
  [ $APPLY -eq 1 ] && dd if=/dev/random bs=32 count=1 2>/dev/null | zfs create $EK -o recordsize=$rs \
      -o primarycache=metadata -o secondarycache=none -o logbias=throughput "$POOL/$n"
done
# swap zvol: own area, 4K blocks, encrypted one-time key, not compressed
echo "+ ephemeral key -> zfs create -V $SWAP_SIZE $POOL/swap"
[ $APPLY -eq 1 ] && dd if=/dev/random bs=32 count=1 2>/dev/null | zfs create -V $SWAP_SIZE $EK \
    -o volblocksize=4K -o compression=off -o sync=always -o primarycache=metadata \
    -o secondarycache=none -o logbias=throughput "$POOL/swap"
run swapon "/dev/zvol/$POOL/swap"
[ $APPLY -eq 1 ] && { swapinfo | grep -q "zvol/$POOL/swap" || die "zvol swap not active; bridge swap left on"; }
swapinfo | grep -q "$BRIDGE.eli" && run swapoff "/dev/$BRIDGE.eli"   # fstab line stays commented
run zfs create -o sync=disabled -o recordsize=1M "$POOL/scratch"   # scratch: rebuilt at boot only if separately approved
# ARC: runtime only, not persisted (loader.conf change needs separate approval)
run sysctl vfs.zfs.arc.max=$ARC_MAX vfs.zfs.arc.min=$ARC_MIN

# --- bounded benchmark ---
[ $APPLY -eq 1 ] || { echo "DRY RUN complete; nothing changed."; exit 0; }
cd /$POOL/scratch
if [ $BENCH = fio ]; then
  for j in "seqread read 1m 1" "seqwrite write 1m 1" "rr4k-qd1 randread 4k 1" "rr4k-qd32 randread 4k 32"; do
    set -- $j
    fio --name=$1 --rw=$2 --bs=$3 --iodepth=$4 --ioengine=posixaio --size=$BENCH_SIZE --runtime=$BENCH_TIME \
        --time_based=0 --refill_buffers --output-format=json --output="$OUT/fio-$1.json" --filename=bench.dat
  done
else
  dd if=/dev/random of=bench.dat bs=1m count=4096 2> "$OUT/dd-write.txt"
  zpool export $POOL; zpool import $POOL        # drop cache before read
  dd if=/$POOL/scratch/bench.dat of=/dev/null bs=1m 2> "$OUT/dd-read.txt"
fi
rm -f /$POOL/scratch/bench.dat
{ zpool status $POOL; zfs get -r recordsize,compression,primarycache,sync,encryption $POOL; sysctl vfs.zfs.arc.max vfs.zfs.arc.min; } > "$OUT/after.txt"
command -v smartctl >/dev/null && smartctl -a "/dev/$DEV" > "$OUT/smart-after.txt" 2>&1
echo "results in $OUT"
