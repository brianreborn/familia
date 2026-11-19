# swarm: angel transport abstraction + LAN baseline (lossy-link leases, BT dongle)

Issue: https://github.com/brianreborn/familia/issues/386
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:24 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

# angel transport abstraction + LAN baseline (read-only)

Linked: umbrella #382, design #380, issue #386.
Did not touch ci-angel, ~/ci/github-act-runner, ada1, NTFS, or fstab.
No kldload, no device attach/detach, no pairing.

## Host
stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct
uname: FreeBSD amd64 15.1-RELEASE-p6

## LAN baseline
### ifconfig (brief)
$ ifconfig -u 2>/dev/null | head -80 || ifconfig 2>/dev/null | head -80
rc=0
em0: flags=1008843<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST,LOWER_UP> metric 0 mtu 1500
	options=4e524bb<RXCSUM,TXCSUM,VLAN_MTU,VLAN_HWTAGGING,JUMBO_MTU,VLAN_HWCSUM,LRO,WOL_MAGIC,VLAN_HWFILTER,VLAN_HWTSO,RXCSUM_IPV6,TXCSUM_IPV6,HWSTATS,MEXTPG>
	ether 34:17:eb:a2:c7:58
	inet 192.168.4.25 netmask 0xfffffc00 broadcast 192.168.7.255
	inet6 fe80::3617:ebff:fea2:c758%em0 prefixlen 64 scopeid 0x1
	inet6 fde5:9bff:5d78:1:3617:ebff:fea2:c758 prefixlen 64 autoconf pltime 604800 vltime 2592000
	media: Ethernet autoselect (1000baseT <full-duplex>)
	status: active
	nd6 options=23<PERFORMNUD,ACCEPT_RTADV,AUTO_LINKLOCAL>
lo0: flags=1008049<UP,LOOPBACK,RUNNING,MULTICAST,LOWER_UP> metric 0 mtu 16384
	options=680003<RXCSUM,TXCSUM,LINKSTATE,RXCSUM_IPV6,TXCSUM_IPV6>
	inet 127.0.0.1 netmask 0xff000000
	inet6 ::1 prefixlen 128
	inet6 fe80::1%lo0 prefixlen 64 scopeid 0x2
	groups: lo
	nd6 options=21<PERFORMNUD,AUTO_LINKLOCAL>


### default route
$ netstat -rn 4 2>/dev/null | head -20 || netstat -rn 2>/dev/null | head -20
rc=124
stderr:
timeout

### ping miryam 192.168.4.29
$ ping -c 3 -W 2000 192.168.4.29 2>&1
rc=0
PING 192.168.4.29 (192.168.4.29): 56 data bytes
64 bytes from 192.168.4.29: icmp_seq=0 ttl=64 time=2.427 ms
64 bytes from 192.168.4.29: icmp_seq=1 ttl=64 time=3.061 ms
64 bytes from 192.168.4.29: icmp_seq=2 ttl=64 time=4.030 ms

--- 192.168.4.29 ping statistics ---
3 packets transmitted, 3 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 2.427/3.173/4.030/0.659 ms


### ping galaxy1 192.168.4.21
$ ping -c 3 -W 2000 192.168.4.21 2>&1
rc=2
PING 192.168.4.21 (192.168.4.21): 56 data bytes

--- 192.168.4.21 ping statistics ---
3 packets transmitted, 0 packets received, 100.0% packet loss


### ping galaxy2 192.168.4.22
$ ping -c 3 -W 2000 192.168.4.22 2>&1
rc=2
PING 192.168.4.22 (192.168.4.22): 56 data bytes

--- 192.168.4.22 ping statistics ---
3 packets transmitted, 0 packets received, 100.0% packet loss


## Bluetooth hardware (inventory only)
### pciconf bluetooth-ish
$ pciconf -lv 2>/dev/null | grep -i -A4 -E 'bluetooth|broadcom.*bcm.*802.11|atheros.*bluetooth' || true
rc=0

### pciconf network/wireless lines
$ pciconf -lv 2>/dev/null | grep -i -E ' class = (network|serialbus)|Bluetooth|802\.11|USB' | head -40
rc=0
    device     = '8 Series/C220 Series Chipset Family USB xHCI'
    subclass   = USB
    device     = '8 Series/C220 Series Chipset Family USB EHCI'
    subclass   = USB
    device     = '8 Series/C220 Series Chipset Family USB EHCI'
    subclass   = USB


### usbconfig
$ usbconfig 2>/dev/null | head -60
rc=0
No device match or lack of permissions.


### usbconfig grep bt
$ usbconfig 2>/dev/null | grep -i -E 'bluetooth|broadcom|realtek|atheros|ubt|cambridge|intel' || true
rc=0

### kldstat (bt/ng/usb)
$ kldstat 2>/dev/null
rc=0
Id Refs Address                Size Name
 1  102 0xffffffff[number]fbe30 kernel
 2    1 0xffffffff82c[number]ae0 fusefs.ko
 3    1 0xffffffff82e[number]a410 i915kms.ko
 4    2 0xffffffff82c[number]f430 drm.ko
 5    1 0xffffffff82cd[number]b8 iic.ko
 6    2 0xffffffff82cd[number] linuxkpi_video.ko
 7    3 0xffffffff82cde[number] dmabuf.ko
 8    3 0xffffffff82ce[number] lindebugfs.ko
 9    1 0xffffffff82cea000     c358 ttm.ko
10    1 0xffffffff82cf[number] acpi_wmi.ko
11    1 0xffffffff82cfb[number]e8 hcons.ko
12    3 0xffffffff82cfe[number]a8 hidmap.ko
13    1 0xffffffff82d[number]e8 hms.ko
14    1 0xffffffff82d[number]e8 hsctrl.ko
15    1 0xffffffff82d[number] ichsmb.ko
16    1 0xffffffff82d0d[number] smbus.ko
17    1 0xffffffff82d[number] linux.ko
18    2 0xffffffff82d[number]da8 mqueuefs.ko
19    4 0xffffffff82d4a000     cdc8 linux_common.ko
20    1 0xffffffff82d[number]f300 linux64.ko
21    1 0xffffffff82d[number] pty.ko
22    1 0xffffffff82d8a[number] fdescfs.ko
23    1 0xffffffff82d8e[number]c0 linprocfs.ko
24    1 0xffffffff82d[number]c linsysfs.ko
25    1 0xffffffff82d9b000    64c08 pf.ko
26    1 0xffffffff8304b000     2a80 mac_ntpd.ko
27    1 0xffffffff[number]f2c58 zfs.ko


### ng_ubt / ubt nodes
$ sysctl -a 2>/dev/null | grep -i -E 'bluetooth|ng_ubt' | head -20; ls /dev/ubt* /dev/ngctl* 2>/dev/null || true
rc=0


## Pluggable transport interface (design)
Path B should call a small interface, not a named channel. Stdlib-shaped:

  transport_id, peer_id, mtu, reliable (bool), rtt_hint_ms
  open(peer) -> handle or wouldblock
  send(handle, bytes) -> sent | queued | err
  recv(handle, max) -> bytes | empty | err
  close(handle)
  probe() -> caps (no side effects)

Channels that implement it: lan-tcp, wifi-direct-tcp, bluetooth-rfcomm,
bluetooth-ble-gatt, sms, mms. The worker picks any channel that is up.
GitHub remains a sink when WAN exists; it is not required for local send.

## Envelope format
ASCII, one record, no secrets:

  F1 <type> <runner> <repo>#<issue> g <gen> u <lease-until-Z> h <hash8>

Types: c=claim, h=heartbeat, r=reap, o=result, q=query. Large results are
chunked (n/N) or stored and forwarded. hash8 covers the fields plus a
host-local key that never leaves the device.

## Lease / claim on lossy links (aligned with #380)
- Expiry uses forge time when the forge is reachable; when isolated,
  peers treat leases as advisory and still fence on generation tokens.
  Local wall clocks are not used to declare expiry.
- Holder self-fences at lease_end minus a margin larger than send+ack
  latency (SMS may need minutes; LAN can use seconds).
- A delayed heartbeat is not a reap. Reap only after lease_end plus the
  margin, and only for that exact generation.
- Idempotency key: (issue, approved SHA or issue-rev, generation).
- Duplicate claims: earliest unexpired claim (forge created_at, else
  arrival + tie-break by runner nonce) wins; losers strike their claim.
- Store-and-forward outbox is flushed in gen order when a channel returns.

## LAN baseline note
Ping figures in the probe above are the measured baseline on the existing
LAN. No routes or firewall rules were changed. 192.168.4.55 was not probed.

## 2. Local model draft (unverified)

## Feasibility Verdict

The feasibility of designing a pluggable transport abstraction for SMS, MMS, Wi-Fi Direct, Bluetooth, and LAN on FreeBSD is feasible. The existing network interfaces and protocols provide the necessary components to implement these transports. The design of the transport abstraction will allow for a flexible and extensible system that can be easily integrated with other child issues.

## Root-Free Path or Named Blockers

There are no root-free paths or named blockers for this design. The design is self-contained and does not require any external dependencies or permissions.

## How Claim/Lease/Heartbeat/Result Envelopes Map Onto This Channel

The claim, lease, heartbeat, and result envelopes will be mapped onto the existing network interfaces and protocols. The claim envelope will be used to request a lease from the network, the lease envelope will be used to hold the lease, the heartbeat envelope will be used to keep the lease alive, and the result envelope will be used to send the result of the operation.

## Open Questions

- The feasibility of implementing the claim, lease, heartbeat, and result envelopes on the existing network interfaces and protocols.
- The feasibility of handling lossy links and asymmetric margins.
- The feasibility of handling idempotency and what happens when a heartbeat is delayed rather than lost.

-- swarm/angel
