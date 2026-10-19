# Phone system agents: Samsung Bixby and Android Gemini

Research for [#80](https://github.com/brianreborn/familia/issues/80), done 2026-10-19.
Web research only. **No phone was touched**: phone7 and phone8 are out of range,
and nothing was installed anywhere. Every "works" below means "documented by the
cited source", not "measured by us". Items marked **(unverified)** come from
community reports or are our inference and need a live test.

## TL;DR

* Neither Bixby nor the Gemini app has a public request/response API that a
  Termux process can call. You can drive the assistant apps through their UI, or
  use Gemini Nano through Google's ML Kit GenAI APIs. ML Kit is a Java/Kotlin API
  that only an Android app can call, so it needs a small companion APK.
* **Root is not necessary, and on modern phones it makes things worse.**
  Unlocking the bootloader (which rooting needs) turns Gemini Nano off. Google
  documents this ([ML Kit get-started][mlkit-start]). On Samsung it also trips the
  Knox e-fuse for good ([Knox FAQ][knox-faq]).
* **Shizuku is the baseline** (ADB-shell rights through wireless debugging, with
  no root). It covers everything the no-root route can reach: launching the
  assistants, injecting text and keys, reading the screen with `uiautomator`,
  choosing the default assistant, and testing AppFunctions with `cmd app_function`.
  The only things root adds beyond Shizuku are Shizuku starting on its own after a
  reboot, and reaching private app data or hooks, which the terms forbid for
  Gemini Nano.

## Root verdict: what root adds beyond Shizuku

| Path | No root (plain app / Termux) | Shizuku (ADB shell, uid 2000) | Root adds beyond Shizuku | Root cost |
|---|---|---|---|---|
| Gemini app (cloud) | Open it, `ACTION_SEND` text to `com.google.android.apps.bard`: opens with text, may not submit ([SO][so-gemini]) | + `input text/keyevent` to submit, `uiautomator dump` to read the reply, `am start` with no Termux UI focus problems | Nothing a user needs. Reading its private DB is possible but fragile and undocumented | Play Integrity may fail, so Google apps may degrade **(unverified for Gemini app itself)** |
| Gemini Nano (on-device, AICore) | Only from an Android app using ML Kit GenAI ([Prompt API][mlkit-prompt]) on a supported device | Same. Shizuku cannot add callers to AICore's allowlist ([privacy blog][pcc-blog]: AICore talks only to PCC-compliant packages; ML Kit is the supported path) | **Negative.** "this API does not support devices with unlocked bootloaders" ([ML Kit][mlkit-start], [Android Authority][aa-bl]). Community workarounds spoof key attestation (TrickyStore etc.) and break with updates ([piunikaweb][piuni]). Pulling the weights is prohibited ([ML Kit GenAI terms][mlkit-terms]) | Loses Gemini Nano entirely |
| Bixby voice / new Bixby (One UI 8.5) | Launch the app; Bixby Routines can trigger Tasker-style apps but cannot send Termux `RUN_COMMAND` itself ([Termux wiki][termux-rc], [r/termux][reddit-bixby]) | + launch, inject text, read the screen as above | Nothing documented. Intercepting the assistant or hooking Bixby would need Xposed **(unverified, not recommended)** | Knox e-fuse trips for good: Samsung Pay/Wallet, Secure Folder, Pass, Knox services stop ([Knox FAQ][knox-faq], [Knox KBA][knox-kba]). Galaxy AI features: mixed reports ([r/androidroot][reddit-gai]) |
| Bixby capsules (Developer Studio) | Cloud-hosted capsules; Studio's last release is 8.23.0 in 2024 ([release notes][bixby-rn]). Users reported in Oct 2024 that capsules and the Marketplace were gone ([r/Bixby][reddit-caps]) **(unverified)** | Not applicable (cloud) | Not applicable | — |
| AppFunctions (Android 16+) | The Gemini → app pipeline is in private preview for trusted testers only ([AppFunctions][appfn]) | `adb shell cmd app_function list-app-functions / execute-app-function` is the documented test path ([AppFunctions][appfn]) | Nothing documented | — |
| Shizuku itself | — | Must be restarted after every reboot ([Shizuku setup][shizuku-setup]) | Starts by itself after boot | — |

**Verdict: root is not necessary.** Shizuku gives the same reach as a PC ADB
shell, which is everything the documented no-root routes need. Root's only real
gain is a Shizuku that starts by itself after a reboot. Against that it costs
Gemini Nano, trips the Knox fuse for good on Samsung, needs a bootloader unlock
that wipes data, loses OTAs, and is often impossible on carrier-locked US
Samsungs **(the last point is a widely reported community fact, not checked per
model)**. familia therefore goes ahead with Phase 2 on Shizuku and does not root.

## Bixby

* **New Bixby (One UI 8.5, Feb 2026):** a conversational "device agent" that
  changes Galaxy settings in plain language and uses Perplexity for live web
  answers. It launched in select markets ([Samsung press][bixby-85],
  [Android Authority][aa-85]). Web answers go to the cloud (Samsung and
  Perplexity). How much of the settings control runs on the device is not stated
  **(unverified)**.
* **Capsules / Bixby Developer Studio:** the docs are still online, and the
  deprecation table runs through R23J ([deprecations][bixby-dep]). There has been
  no Studio release since 8.23.0 (2024). Treat it as stagnant: there's nothing to
  wire into.
* **Modes and Routines (and Good Lock Routine+):** they can open apps and run
  Samsung actions. No documented action sends an arbitrary intent or runs a shell
  command, so Termux can only be reached through a helper app such as Tasker
  ([r/termux][reddit-bixby]). The useful direction is the reverse: a Routine
  *opens* a familia-triggering app or shortcut.
* **Accessibility:** a third-party AccessibilityService can read and drive Bixby's
  UI. Shizuku's `uiautomator dump` + `input` does the same from Termux without
  installing anything extra.
* **Galaxy AI:** "Process data only on device" setting exists on supported
  flagships (One UI 6.1+) ([Samsung support][sam-gai], [Knox data-processing][knox-gai]).
  Samsung documents no public developer API to its own on-device models.
  On recent Samsungs, the documented on-device LLM route for third-party apps is
  Gemini Nano through ML Kit: the Galaxy S25/S26 and Z Fold7/Flip8 families are on
  Google's supported-device list ([ML Kit GenAI][mlkit-overview]).
* **Package name:** we found no Samsung documentation of Bixby voice package names
  or intents. The adapter therefore finds the package at runtime with
  `cmd package resolve-activity` / `pm list packages` and never hard-codes one.

## Gemini on Android

* **Gemini app (cloud):** needs Android 10+ (Google's help page says 9+) and at
  least 2 GB RAM, not Android Go ([Gemini help][gem-req], [Android Authority][aa-gem10]).
  There is no public intent that both prefills and submits a prompt.
  `ACTION_SEND` with `text/plain` opens it with the text. Submitting needs UI
  input ([SO][so-gemini], [SO 2][so-gemini2]). Prompts go to Google under the
  signed-in account. User age is 13+.
* **Gemini Nano via AICore + ML Kit GenAI:**
  * The Prompt API (`com.google.mlkit:genai-prompt:1.0.0-beta4`) needs API 26+, a
    supported device, a locked bootloader and AICore. It's beta with no SLA
    ([get-started][mlkit-start], [Prompt API][mlkit-prompt]).
  * Supported devices are 2024+ flagships only (Pixel 9+, Galaxy S25/S26, Z Fold7,
    OnePlus 13, and others) ([device list][mlkit-overview]).
  * nano-v3 shares Gemma 3n's architecture, so open Gemma 3n is Google's own
    stand-in for prototyping ([Android blog][mlkit-blog]). That stand-in already
    fits familia's llama.cpp nodes.
  * Inference is on-device, and AICore keeps no record of inputs or outputs
    ([privacy blog][pcc-blog]). ML Kit does send metrics data, which the app must
    disclose ([terms][mlkit-terms]).
* **Termux vs companion app:** Termux cannot link ML Kit. A companion APK
  (Kotlin, ML Kit dependency) could expose Nano to Termux over a local intent or
  socket. **No such APK exists in familia, none is being built, and none will be
  installed without approval.** The adapter has a `nano` transport that only
  reports "companion app not present".
* **Direct use of the Nano weights/runtime:** not allowed. The ML Kit GenAI terms
  forbid extracting parameter weights, getting around technical restrictions, and
  building competing models ([terms][mlkit-terms]).
* **AppFunctions:** Android 16+, with Gemini integration in private preview
  ([AppFunctions][appfn]). Not usable by us today.

## Shizuku (baseline)

* **License:** Apache-2.0, with extra name, icon and app-id restrictions under
  §6 ([README][shizuku-readme]).
* **Distribution:** the official download page lists the IzzyOnDroid F-Droid
  repo and Coolapk ([download][shizuku-dl]), plus GitHub releases at
  RikkaApps/Shizuku. It is also on Google Play. Per the user's preference, familia
  documents only GitHub/IzzyOnDroid.
* **Start:**
  * Android 11+: wireless debugging, pair once, then start, with no PC needed.
  * Android ≤10: `adb shell sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh`
    from a computer (miryam can do this over USB or `adb tcpip`).
  * **Either way it must be started again after every reboot unless rooted**
    ([setup][shizuku-setup]).
* **Termux bridge:** `rish`, exported from the Shizuku app with `rish_shizuku.dex`
  ([rish README][rish]). Set `RISH_APPLICATION_ID=com.termux`. On Android 14+ the
  dex must sit in Termux's private home and be non-writable. `rish -c 'cmd'` runs
  as uid 2000 (shell).
* **How familia detects it:** `rish -c id` printing `uid=2000` means it's running.
  A missing rish or an error means it's stopped. The monitor reports
  `shizuku: running|stopped|absent`, and "stopped after reboot" is the expected
  state, not a crash.

## Licenses and terms (for `scripts/licenses.py`)

| Path | What the user agrees to |
|---|---|
| Shizuku / rish | Apache-2.0 (+§6 name/icon restrictions) |
| Gemini app | Google Terms of Service, Gemini Apps Privacy Notice, [Generative AI Prohibited Use Policy][gen-pup]; 13+ |
| Gemini Nano (ML Kit) | Google APIs Terms + [ML Kit GenAI Additional Terms][mlkit-terms]: 18+, no production use of Preview, no weight extraction, no bypassing safety filters, no medical use |
| Bixby / Galaxy AI | Samsung account terms and Samsung privacy notice; new Bixby web answers involve Perplexity **(the exact terms text was not reviewed)** |

## Privacy: what leaves the device

| Path | Leaves the device | Account |
|---|---|---|
| Gemini app | The prompt, reply and any screen content you share | Google account |
| Gemini Nano | No prompt data. ML Kit metrics only | none for inference |
| Bixby / new Bixby | Voice/text to Samsung; web questions to Perplexity | Samsung account |
| Galaxy AI with "on device only" | Nothing for on-device features | Samsung account |
| Shizuku | Nothing (local ADB over loopback/Wi-Fi) | none |

familia treats Gemini app and Bixby as **cloud-backed**: every call needs consent.

## Old phones (phone7 / phone8)

Model numbers are not recorded here (no device IDs in the public repo). To check,
run `getprop ro.build.version.release`, `getprop ro.product.model` and
`getprop ro.board.platform` on each phone:

| Needs | Requirement |
|---|---|
| Shizuku without a PC | Android 11+ (wireless debugging) |
| Shizuku with miryam as the PC | Android 6+ (Shizuku's API floor **unverified**; ≤10 uses `adb`) |
| Gemini app | Android 10+, ≥2 GB RAM, not Go |
| Bixby (any) | Samsung, One UI; new Bixby needs One UI 8.5 |
| Gemini Nano | A 2024+ flagship from the list, with the bootloader locked. **A ~15-year-old phone will not qualify**, so that role stays with Gemma 3n / small GGUFs on llama.cpp |

## Sources

- `mlkit-start`: <https://developers.google.com/ml-kit/genai/prompt/android/get-started>
- `mlkit-prompt`: <https://developers.google.com/ml-kit/genai/prompt/android>
- `mlkit-overview`: <https://developers.google.com/ml-kit/genai>
- `mlkit-blog`: <https://developer.android.com/blog/posts/ml-kit-s-prompt-api-unlock-custom-on-device-gemini-nano-experiences>
- `mlkit-terms`: <https://developers.google.com/ml-kit/genai-terms>
- `pcc-blog`: <https://android-developers.googleblog.com/2024/10/introduction-to-privacy-and-safety-gemini-nano.html>
- `aa-bl`: <https://www.androidauthority.com/gemini-nano-bootloader-3605497/>
- `piuni`: <https://piunikaweb.com/2024/09/03/pixel-9-enable-ai-features-on-unlocked-bootloader-devices/>
- `knox-faq`: <https://docs.samsungknox.com/admin/knox-platform-for-enterprise/faq/>
- `knox-kba`: <https://docs.samsungknox.com/admin/knox-platform-for-enterprise/kbas/kba-115013151307/>
- `knox-gai`: <https://docs.samsungknox.com/admin/knox-platform-for-enterprise/knox-service-plugin/configure-advanced-policies/data-processing-for-galaxy-ai/>
- `reddit-gai`: <https://www.reddit.com/r/androidroot/comments/1c6mfwe/will_galaxy_ai_features_will_be_lost_after_rooting/>
- `bixby-rn`: <https://corp.bixbydevelopers.com/dev/docs/dev-guide/release-notes/bixby-studio>
- `bixby-dep`: <https://bixbydevelopers.com/dev/docs/dev-guide/release-notes/deprecations>
- `reddit-caps`: <https://www.reddit.com/r/Bixby/comments/1fxb1x8/capsules_are_gone/>
- `bixby-85`: <https://www.samsungmobilepress.com/articles/bixby-one-ui-8-5-conversational-device-agent>
- `aa-85`: <https://www.androidauthority.com/one-ui-8-5-stable-3643086/>
- `sam-gai`: <https://www.samsung.com/us/support/answer/ANS10000753/>
- `termux-rc`: <https://github.com/termux/termux-app/wiki/RUN_COMMAND-Intent>
- `reddit-bixby`: <https://www.reddit.com/r/termux/comments/pf4rzi/what_is_the_shortestrobust_way_to_launch_a_termux/>
- `so-gemini`: <https://stackoverflow.com/questions/78635448/how-to-launch-android-gemini-app-with-an-initial-query>
- `so-gemini2`: <https://stackoverflow.com/questions/79832192/auto-paste-text-into-chatgpt-gemini-from-android-app>
- `gem-req`: <https://support.google.com/gemini/answer/14579026>
- `aa-gem10`: <https://www.androidauthority.com/gemini-app-support-older-android-devices-3435980/>
- `gen-pup`: <https://support.google.com/gemini/answer/16625148>
- `appfn`: <https://developer.android.com/ai/appfunctions>
- `shizuku-setup`: <https://shizuku.rikka.app/guide/setup/>
- `shizuku-dl`: <https://shizuku.rikka.app/download/>
- `shizuku-readme`: <https://github.com/RikkaApps/Shizuku>
- `rish`: <https://github.com/RikkaApps/Shizuku-API/blob/master/rish/README.md>

[mlkit-start]: https://developers.google.com/ml-kit/genai/prompt/android/get-started
[mlkit-prompt]: https://developers.google.com/ml-kit/genai/prompt/android
[mlkit-overview]: https://developers.google.com/ml-kit/genai
[mlkit-blog]: https://developer.android.com/blog/posts/ml-kit-s-prompt-api-unlock-custom-on-device-gemini-nano-experiences
[mlkit-terms]: https://developers.google.com/ml-kit/genai-terms
[pcc-blog]: https://android-developers.googleblog.com/2024/10/introduction-to-privacy-and-safety-gemini-nano.html
[aa-bl]: https://www.androidauthority.com/gemini-nano-bootloader-3605497/
[piuni]: https://piunikaweb.com/2024/09/03/pixel-9-enable-ai-features-on-unlocked-bootloader-devices/
[knox-faq]: https://docs.samsungknox.com/admin/knox-platform-for-enterprise/faq/
[knox-kba]: https://docs.samsungknox.com/admin/knox-platform-for-enterprise/kbas/kba-115013151307/
[knox-gai]: https://docs.samsungknox.com/admin/knox-platform-for-enterprise/knox-service-plugin/configure-advanced-policies/data-processing-for-galaxy-ai/
[reddit-gai]: https://www.reddit.com/r/androidroot/comments/1c6mfwe/will_galaxy_ai_features_will_be_lost_after_rooting/
[bixby-rn]: https://corp.bixbydevelopers.com/dev/docs/dev-guide/release-notes/bixby-studio
[bixby-dep]: https://bixbydevelopers.com/dev/docs/dev-guide/release-notes/deprecations
[reddit-caps]: https://www.reddit.com/r/Bixby/comments/1fxb1x8/capsules_are_gone/
[bixby-85]: https://www.samsungmobilepress.com/articles/bixby-one-ui-8-5-conversational-device-agent
[aa-85]: https://www.androidauthority.com/one-ui-8-5-stable-3643086/
[sam-gai]: https://www.samsung.com/us/support/answer/ANS10000753/
[termux-rc]: https://github.com/termux/termux-app/wiki/RUN_COMMAND-Intent
[reddit-bixby]: https://www.reddit.com/r/termux/comments/pf4rzi/what_is_the_shortestrobust_way_to_launch_a_termux/
[so-gemini]: https://stackoverflow.com/questions/78635448/how-to-launch-android-gemini-app-with-an-initial-query
[so-gemini2]: https://stackoverflow.com/questions/79832192/auto-paste-text-into-chatgpt-gemini-from-android-app
[gem-req]: https://support.google.com/gemini/answer/14579026
[aa-gem10]: https://www.androidauthority.com/gemini-app-support-older-android-devices-3435980/
[gen-pup]: https://support.google.com/gemini/answer/16625148
[appfn]: https://developer.android.com/ai/appfunctions
[shizuku-setup]: https://shizuku.rikka.app/guide/setup/
[shizuku-dl]: https://shizuku.rikka.app/download/
[shizuku-readme]: https://github.com/RikkaApps/Shizuku
[rish]: https://github.com/RikkaApps/Shizuku-API/blob/master/rish/README.md
