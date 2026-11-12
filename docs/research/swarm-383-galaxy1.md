# swarm: galaxy1 Wi-Fi Direct transport (root-free Termux/Android P2P)

Issue: https://github.com/brianreborn/familia/issues/383
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=21894 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 15:44 PST

Status: first pass by the phone swarm worker. Section 1 is a read-only
probe run on the phone (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

# galaxy1 Wi-Fi Direct probe (read-only)

Linked: umbrella #382, design #380, issue #383.
No P2P group was formed. No pairing changes.

## Host
stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=21894 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct
uname: Linux aarch64 6.12.69-android16-6-p902157d-abogkiA576USQS4BZJ2-4k

## Capability probe
### device model
$ getprop ro.product.model; getprop ro.build.version.release; getprop ro.build.version.sdk
rc=0
SM-A576U
17
37


### wifi / p2p props
$ getprop | grep -i -E 'p2p|wifidirect|wifi.direct|wfd.|wlan' | head -80
rc=0
[init.svc.wland]: [running]
[ro.hw.wfd_use_c2_encoder]: [1]
[ro.hw.wfd_use_single_plane_in_drm]: [0]
[ro.security.wlan.release]: [2]
[ro.security.wlan.ver]: [1.0]
[ro.vendor.hdm.bootblock.wlan]: [false]
[vendor.wifi.dualconcurrent.interface]: [swlan0]


### net ifaces
$ ip -br link 2>/dev/null || ip link 2>/dev/null || ifconfig -a 2>/dev/null | head -80
rc=0
lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0
        unspec [number]  txqueuelen 1000  (UNSPEC)

wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.4.21  netmask 255.255.252.0  broadcast 192.168.7.255
        unspec [number]  txqueuelen 4000  (UNSPEC)



### tools present
$ command -v dumpsys; command -v cmd; command -v iw; command -v wpa_cli; command -v iwconfig; command -v termux-wifi-connectioninfo; command -v termux-wifi-scaninfo
rc=0
/bin/dumpsys
/data/data/com.termux/files/usr/bin/cmd
/data/data/com.termux/files/usr/bin/termux-wifi-connectioninfo
/data/data/com.termux/files/usr/bin/termux-wifi-scaninfo


### dumpsys wifip2p (head)
$ dumpsys wifip2p 2>/dev/null | head -120
rc=0

### dumpsys wifi p2p lines
$ dumpsys wifi 2>/dev/null | grep -i -E 'p2p|wifidirect|wifi.direct' | head -40
rc=0

### cmd wifi help (head)
$ cmd wifi help 2>/dev/null | head -40
rc=0

### termux-wifi-connectioninfo
$ termux-wifi-connectioninfo
rc=124
stderr:
timeout

## Root-free path (feasibility)
Android Wi-Fi Direct is exposed to apps via WifiP2pManager. Termux has no
first-party P2P command. Root-free options:
1. A small companion app or existing Android Wi-Fi Direct UI (Settings ->
   Wi-Fi Direct / Wi-Fi+ -> Wi-Fi Direct) to form a group, then a TCP
   socket on the P2P interface (typically 192.168.49.0/24, group owner
   often .1). Termux can use that IP once the link is up.
2. dumpsys/cmd wifi may show state without root, but forming a group
   from the shell usually needs an app permission (NEARBY_WIFI_DEVICES
   / location on older APIs) and a user-visible consent.
3. wpa_cli p2p_* often needs access to the system wpa_supplicant socket,
   which stock Android does not grant Termux (root or a privileged helper).
Blockers to confirm from the probe above: whether dumpsys wifip2p is
readable, whether a p2p0 iface already exists, and permission errors.

## Throughput / latency sketch
No new P2P session was started, so no on-device measurement this run.
Typical published Wi-Fi Direct figures (IEEE 802.11-based; typical, not measured here):
- Setup / discovery: often 1-5 seconds when both peers are in range and awake.
- Throughput: commonly tens to a few hundred Mbit/s in good range (similar
  order to local 802.11; OEM and band dependent).
- Latency: millisecond-to-tens-of-milliseconds once associated, like a short
  Wi-Fi hop; much worse if a peer is dozing.
Sources: Wi-Fi Alliance Wi-Fi Direct FAQ / typical 802.11 characteristics;
Android WifiP2pManager docs. Replace with measured numbers only after an
approved test group is formed.

## Envelope mapping
Once a P2P IP is up, carry the same JSON/ASCII envelope as LAN TCP:
claim, heartbeat, reap, result. MTU is large enough that a claim line
fits in one packet. Store-and-forward: write ~/swarm/outbox if the peer
is missing; flush when the P2P or WAN/GitHub path returns. Doze and the
Android phantom-process killer can freeze Termux; lease expiry plus a
pre-side-effect re-check (design #380) is the recovery path.

## 2. Local model draft (unverified)

Answer: Feasible. Root-free paths exist in Android P2P. Enough to form a group and a link. The envelope is carried via a compact envelope protocol, which Android P2P can handle. The envelope carries the claim, lease, heartbeat, and result. Throughput is unknown but <100 kbps typical for P2P; latency ~50ms. The result envelope is carried by the group owner (galaxy1).

End of note.

 [end of text]

-- swarm/galaxy1
