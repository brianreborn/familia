# swarm: galaxy2 SMS/MMS transport (termux-api, limits, signed envelopes)

Issue: https://github.com/brianreborn/familia/issues/384
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 05:14 PST
Approved-content-sha256: 118a1a6e9de339a52350b9abb063d71dd50271dd9e8219f3470b984cd1163bb2

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (none); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

# galaxy2 SMS/MMS probe (read-only, no messages sent, inbox not dumped)

Linked: umbrella #382, design #380, issue #384.
No SMS or MMS was sent. termux-sms-list was not invoked (privacy).

## Host
stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live
uname: Linux aarch64 6.12.69-android16-6-p902157d-abogkiA576USQS4BZJ2-4k

## Tool presence
### termux-api tools
$ command -v termux-sms-send; command -v termux-sms-list; command -v termux-sms-inbox; command -v termux-telephony-deviceinfo; command -v termux-mms-send; ls $PREFIX/bin/termux-sms-* $PREFIX/bin/termux-mms-* 2>/dev/null
rc=2
/data/data/com.termux/files/usr/bin/termux-sms-send
/data/data/com.termux/files/usr/bin/termux-sms-list
/data/data/com.termux/files/usr/bin/termux-sms-inbox
/data/data/com.termux/files/usr/bin/termux-telephony-deviceinfo
/data/data/com.termux/files/usr/bin/termux-sms-inbox
/data/data/com.termux/files/usr/bin/termux-sms-list
/data/data/com.termux/files/usr/bin/termux-sms-send


### termux-api package
$ command -v termux-api-start; pkg list-installed 2>/dev/null | grep -i termux-api || dpkg -l 2>/dev/null | grep -i termux-api
rc=0
/data/data/com.termux/files/usr/bin/termux-api-start
termux-api/stable,now 0.60.0 aarch64 [installed]


### termux-sms-send help
$ termux-sms-send --help 2>&1 | head -40
rc=0
termux-sms-send: illegal option --


### termux-sms-list help only
$ termux-sms-list --help 2>&1 | head -40
rc=0
termux-sms-list command lists SMS conversations and messages.

Usage:
    termux-sms-list [command_options]

Available command_options:
    [ -h | --help ]           Display this help screen.
#    [ --version ]             Display version.
    [ -q | --quiet ]          Set log level to 'OFF'.
    [ -v | -vv | -vvv | -vvvvv ]
                              Set log level to 'DEBUG', 'VERBOSE',
                              'VVERBOSE' and 'VVVERBOSE'.
    [ -c | --conversation-list ]
                              Show SMS conversations list instead of
                              messages list.
                              By default only one SMS message per
                              conversation is returned unless the
                              '--conversation-return-multiple-messages'
                              option is passed.
                              By default all SMS messages are returned
                              as a single array without nesting
                              unless the
                              '--conversation-return-nested-view'
                              option is passed.
    [ --conversation-limit=<limit> ]
                              The SQL limit for returned SMS
                              conversations.
    [ --conversation-offset=<offset> ]
                              The SQL offset for returned SMS
                              conversations.
    [ --conversation-return-multiple-messages ]
                              Return multiple SMS messages per
                              conversation.
    [ --conversation-return-nested-view ]
                              Return a nested object view of
                              conversations where each conversation
                              contains an array of SMS messages with
                              the conversation id as the key.
    [ --conversation-return-no-order-reverse ]
                              Return SMS conversations without


termux-sms-list was not run, so inbox contents were not read.

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

(local model unavailable: llama cli rc=1 0.00.002.891 I llama_completion: llama backend init
0.00.093.089 I llama_completion: load the model and apply lora adapter, if any
0.00.093.225 E gguf_init_from_file: failed to open GGUF file '/data/data/com.termux/files/home/.local/share/gguf/models/general/LFM2.5-1.2B-Instruct-Q4_K_M.gguf' (No suc
... [truncated]
)

-- swarm/galaxy2
