# swarm: galaxy2 SMS/MMS transport (termux-api, limits, signed envelopes)

Issue: https://github.com/brianreborn/familia/issues/384
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:10 PST
Approved-content-sha256: 118a1a6e9de339a52350b9abb063d71dd50271dd9e8219f3470b984cd1163bb2

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

# galaxy2 SMS/MMS probe (read-only, no messages sent, inbox not dumped)

Linked: umbrella #382, design #380, issue #384.
No SMS or MMS was sent. termux-sms-list was not invoked (privacy).

## Host
stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live
uname: Linux x86_64 6.12.113+

## Tool presence
### termux-api tools
$ command -v termux-sms-send; command -v termux-sms-list; command -v termux-sms-inbox; command -v termux-telephony-deviceinfo; command -v termux-mms-send; ls $PREFIX/bin/termux-sms-* $PREFIX/bin/termux-mms-* 2>/dev/null
rc=2

### termux-api package
$ command -v termux-api-start; pkg list-installed 2>/dev/null | grep -i termux-api || dpkg -l 2>/dev/null | grep -i termux-api
rc=1

## Size, rate, cost (typical; not a carrier quote)
- SMS GSM-7: 160 characters per segment; UCS-2 (e.g. most emoji/non-Latin):
  70 characters per segment. Concatenated SMS uses a UDH header, so 153/67
  per segment after the first. Source: 3GPP TS 23.040 (SMS).
- Practical cap: many devices/carriers cap concatenated SMS around 6-10
  segments. Treat anything over ~900 GSM-7 chars as unreliable for SMS.
- MMS can carry a larger body or attachment (often 300 KiB-1 MiB cap,
  carrier-specific; unknown for this SIM until tested). MMS usually needs
  a mobile data path, so it may fail when WAN is down even if SMS works.
- Rate: Android / carriers may throttle bursts (order of one message every
  few seconds, with a short-term cap). Unknown here; do not hammer.
- Cost: US SMS/MMS may be billed per message or included in a plan. Cost
  is unknown until Brian confirms the plan. No test messages were sent.

## Signed compact envelope (fits one GSM-7 SMS)
Claim/heartbeat target: <= 140 GSM-7 chars, ASCII only.

  F1 <runner> c <issue> g <gen> u <lease-until-compact> h <hash8>

Example:
  F1 galaxy2 c 384 g 1 u 20261111T0115Z h ab12cd34

h is an 8-hex digest of the envelope fields plus a host-local key that
never leaves the device (not a GitHub token). Results that do not fit
SMS go to a multi-segment SMS, an MMS body (only when WAN/mobile data
is acceptable), or stay in ~/swarm/outbox until GitHub sync.
Store-and-forward is the default when the other phone is off or the
SMS path fails.

## Guardrail
No real SMS to anyone except between the two phones' own numbers, and
only after Brian confirms those numbers. This run sent zero messages.

## 2. Local model draft (unverified)



-- swarm/box
