# Investigate intermittent network outages on Surface1

Issue: https://github.com/brianreborn/familia/issues/664
Runner: surface1 (stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-22 22:51 PST
Approved-content-sha256: fd64a8c87ee8f9d5226c71a39afe61b16719a785bc5a41d6b2f4ceb8fa99df43

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on surface1)

stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

```markdown
# Issue #664 ? Investigate intermittent network outages on Surface1

## (a) What the issue asks

The host tracked as **`surface1`** in the swarm inventory is intermittently losing network connectivity.  
Even though a read?only probe via the existing `miryam` SSH path can reach it now, earlier periods of ?outage? are not recorded and we need to find out **when**, **how often**, and **why** those gaps happen. The goal is to identify the root cause (Wi?Fi, DHCP/default route, DNS, gateway/WAN, power management, SSH/service availability) and reduce the recurrence without changing topology or exposing new services.

Key unknowns:

- Exact start/end times of past outages.
- Whether failures are network?layer (link, routing, DNS), host?side (power, Wi?Fi association), or service?specific (SSH runner not running).
- If the **Actions runner** is installed and supervised on this host.
- Peer observations from other LAN nodes during the same windows.

## (b) Proposed approach & likely components

1. **Read?only link capture**
   - Run a read?only `ping` / `traceroute` from Miryam to `surface1`.  
   - Capture timestamps, private IPs, and any NAT/port forwarding info.

2. **Route/DNS inspection**
   - Query the host?s routing table (`ip route`) and DNS records for `github.com`, etc., via a read?only command or by inspecting `/etc/network/interfaces` / network manager config.
   - Check kernel logs around outage windows (`dmesg | grep -i net`, `network-manager status`).

3. **Runner/service supervision check**
   - Look for the Actions runner process (e.g., `surface1-runner` or similar) and its supervisor status without starting it.
   - Review any existing crontab / systemd services that might be tied to network tasks.

4. **Peer comparison**
   - From other configured peers, run read?only reachability probes during the same outage windows to see if they also drop or only lose SSH access.

5. **Minimal remediation (proposed)**
   - Verify DHCP lease renewal and default route configuration.
   - Ensure Wi?Fi association is stable; check for power?save states.
   - If a runner process is missing, start it in read?only mode first to confirm supervision.

6. **Verification & rollback**
   - After any change (e.g., forcing DHCP renew or ensuring the runner daemon is running), re?probe and monitor for at least one full interval of stable reachability.
   - Document who approved each step and how to roll back (e.g., stop runner, revert config).

**Files/Components likely involved**

- Swarm inventory entry `surface1` / alias mapping
- Miryam SSH agent / host reachable via it
- Host OS: Linux (`surface7` reported internally)
- Network manager / routing tables
- DNS server configuration (likely system?wide or per?interface)
- Actions runner process & supervision mechanism (not yet seen running)
- Wi?Fi driver / network interface configs

## (c) Risks and test ideas

| Risk | Mitigation |
|------|------------|
| Reading only may miss transient state changes between probes. | Schedule probes at multiple intervals; use `systemctl status` for runner without starting it. |
| Changing DHCP or routing could affect other services. | Make changes minimal, apply only after confirming no critical dependencies (e.g., SSH). Use read?only tools first to verify current values. |
| Misidentifying the cause (e.g., attributing a DNS failure to WAN when it?s local). | Correlate timestamps across multiple probes and host logs; compare with peer behavior. |
| Runner supervision not found could hide service crashes. | Check for orphaned processes, look at `/var/log/` of relevant daemons, use `ps -ef`. |

**Test ideas (no execution yet ? unknown results)**

- Run a read?only `ping -c 3 surface1.example.com` from Miryam and capture start/end times.
- Query `/etc/network/interfaces` or the network manager?s current routes on the host.
- Check for an active runner process: `pgrep -f actions-runner*` (or similar) ? unknown if present.
- Pull recent kernel messages around a known outage window from `dmesg`.
- Compare reachability of `surface1` and other peers via SSH at the same times.

## (d) Open questions

- **Exact timestamps** of past outages: not available in current summary.
- **Current presence/state** of the Actions runner on `surface1`: unknown whether installed or supervised.
- **Network interface configuration**: Wi?Fi vs. wired, DHCP scope, default route target (unknown).
- **Power management settings** that might put the host into sleep during outages.
- **Whether other LAN peers experienced the same window** and what their behavior was.
- **Swarm alias mapping**: `surface7` is reported as OS name; does it differ from `surface1` alias? How does swarm resolve aliases?
- **Approval status** for any remediation (e.g., forcing DHCP renew, enabling runner).

Until these are answered, the diagnosis will rely on evidence gathered via read?only probes and log inspection.
```

-- swarm/surface1
