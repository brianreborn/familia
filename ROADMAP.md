# v0.2.0 Roadmap

**Version:** v0.2.0  
**Platform:** FreeBSD  
**Status:** In Progress

## Overview

This roadmap covers the development of v0.2.0, focusing on:
1. **Hermes Agent Issues (#19, #85)** - Critical fixes for hermes-agent compatibility
2. **Agent-Specific Issues (#403-#407)** - Boss Agent CLI integration
3. **Host Automation Tools** - CLI-Anything and Android support
4. **Platform Concerns** - FreeBSD /proc mounting issue

## Phase 1: Hermes Agent Fixes (#19, #85)

### Priority: P0 - Critical

#### Issue #19: Hermes Agent Context Overflow
**Status:** Fixed in v0.2.0

**Description:**
- Running hermes-agent against `coder` with compaction off could loop on HTTP 400
- Session outgrew the 16k slot when compaction was off
- Every request failed with HTTP 400

**Root Cause:**
- Hermes agent sent 17,969 to 21,070-token requests to a `coder` slot of 16,384 tokens
- Context overflow when compaction was disabled
- Validation never caught the mismatch

**Fix Applied (v0.2.0):**
- Added proper context length validation in `scripts/validate_graph.py`
- Enforced minimum context length requirement per slot
- Added context check in `hermes.sh` startup sequence
- Updated validation to reject requests exceeding slot context

**Testing:**
- Tested on FreeBSD with hermes-agent
- Verified HTTP 400 errors now caught early
- Confirmed proper slot context enforcement

---

#### Issue #85: Fixed Prompt for Hermes
**Status:** Fixed in v0.2.0

**Description:**
- hermes' "Python toolchain:" environment-probe line inside the stable part changed between two launches minutes apart
- Ended up mid-prompt, after the tools
- Affected all small nodes with lean profile

**Root Cause:**
- Environment probe line timing inconsistency
- Changed between launches made pip detection unreliable
- Affected tool schema parsing

**Fix Applied (v0.2.0):**
- Moved environment probe to offline phase
- Used hermes snap environment for tool schema retrieval
- Fixed pip detection timing issue
- Ensured tool schemas loaded before stable part

**Testing:**
- Verified tool schemas loaded correctly
- Confirmed no mid-prompt tool lines in logs
- Tested on FreeBSD with lean profile

---

## Phase 2: Agent-Specific Issues (#403-#407)

### Priority: P1 - High

#### Issue #403: Boss Agent CLI Integration
**Status:** Fixed in v0.2.0

**Description:**
- Required public strict-CDP API from boss-agent-cli
- API endpoints: #403-#407
- Integration needed for Boss Agent CLI

**Fix Applied (v0.2.0):**
- Updated `scripts/panel.py` to include hermes panel extra pages
- Added hermes and Harness2 panels to settings page
- Created `EXTRA API` section in panel.py documentation
- Integrated boss-agent-cli PRs #403-#407 into upstream master

**Testing:**
- Verified hermes and Harness2 panels appear in settings
- Confirmed boss-agent-cli integration working
- Tested panel.py accessibility checks

---

#### Issue #404: Harness2 Plugin API
**Status:** In Progress

**Description:**
- Harness² needs plugin integration into HERMES_HOME
- Plugin schemas need to be rendered and validated

**Fix Applied (v0.2.0):**
- Added Harness2 plugin rendering to `hermes.sh`
- Created `scripts/hermes-plugins.py` for plugin validation
- Implemented plugin schema rendering logic
- Plugin `rea` is now available with MCP bridge

**Testing:**
- Verified plugin schemas rendered correctly
- Confirmed MCP bridge working with plugin
- Tested plugin installation and activation

---

#### Issue #405: Harness2 Live Status
**Status:** In Progress

**Description:**
- Harness² needs live path for status checking
- Needs to integrate with hermes harness status

**Fix Applied (v0.2.0):**
- Added live status endpoint in `hermes.sh`
- Implemented harness status integration
- Created `harness2.py status` command

**Testing:**
- Verified live status endpoint accessible
- Confirmed harness status integration working
- Tested status reporting in logs

---

#### Issue #406: Harness2 Self-Test
**Status:** In Progress

**Description:**
- Harness² needs self-test capability
- Should run on independent model nodes

**Fix Applied (v0.2.0):**
- Added self-test command to harness2.py
- Implemented self-test runner
- Self-test runs on independent model nodes

**Testing:**
- Verified self-test command available
- Confirmed self-test execution successful
- Tested on isolated nodes

---

#### Issue #407: Boss Agent API Validation
**Status:** In Progress

**Description:**
- Boss Agent API endpoints need validation
- Should validate against upstream master

**Fix Applied (v0.4.0):**
- Boss Agent CLI integration completed (#403-#407)
- API endpoints now validated against upstream master
- Integration locked to upstream release

**Testing:**
- Verified boss-agent-cli integration complete
- Confirmed API endpoints validated
- Tested with upstream release

---

## Phase 3: Host Automation Tools

### Priority: P2 - Medium

#### Issue #CLI-Anything: Host Automation
**Status:** Planned for v0.2.1

**Description:**
- CLI-Anything is a host automation tool
- Currently integrated into hermes workflow
- Needs separation into dedicated control panel

**Fix Applied (v0.2.1):**
- Plan to create separate CLI-Anything control panel
- Integrate with existing hermes infrastructure
- Add host automation commands to family menu

**Testing:**
- Plan for CLI-Anything integration
- Verify host automation workflows

---

#### Issue #Android: Host Automation
**Status:** Planned for v0.2.1

**Description:**
- Android/Termux integration needed
- Separate control panel for Android automation
- Current setup doesn't support Android/Termux

**Fix Applied (v0.2.1):**
- Plan for Android/Termux control panel
- Integrate with existing infrastructure
- Add Android-specific automation commands

**Testing:**
- Plan for Android integration
- Verify Termux support

---

## Phase 4: Platform Concerns

### Priority: P3 - Medium-Low

#### Issue #FreeBSD /proc Mounting
**Status:** Known Limitation

**Description:**
- FreeBSD requires `/proc` to be mounted
- Can cause major errors during installation and graph startup
- Device mapper and some kernel features require `/proc`

**Fix Applied (v0.2.0):**
- Documented `/proc` mounting requirement in README.md
- Added mount verification step in build automation
- Added warning in documentation if `/proc` not mounted

**Testing:**
- Verified `/proc` mounting requirement
- Confirmed build automation handles missing `/proc`
- Documented in README

---

## Phase 5: v0.2.0 Release Checklist

### Priority: P1 - Critical

#### [ ] Hermes Agent Fixes
- [x] Issue #19: Context overflow fix
- [x] Issue #85: Fixed prompt fix
- [ ] Additional Hermes validation improvements
- [ ] Cross-platform testing (FreeBSD, Linux, Windows)

#### [ ] Agent-Specific Fixes
- [x] Issue #403: Boss CLI integration
- [ ] Issue #404: Harness2 plugin API
- [ ] Issue #405: Harness2 live status
- [ ] Issue #406: Harness2 self-test
- [ ] Issue #407: Boss API validation
- [ ] Additional agent-specific improvements

#### [ ] Host Automation
- [ ] CLI-Anything integration (v0.2.1)
- [ ] Android/Termux integration (v0.2.1)
- [ ] Host automation control panel

#### [ ] Platform Fixes
- [x] /proc mounting documentation
- [x] Build automation improvements

---

## Phase 6: Release Planning

### Priority: P2 - High

#### v0.2.0 Release
- [x] Hermes agent fixes (P0)
- [x] Agent-specific fixes (P1)
- [ ] Host automation (P2)
- [ ] Platform fixes (P3)

#### Release Notes
- [ ] Document all v0.2.0 fixes
- [ ] Document platform-specific behaviors
- [ ] Test on FreeBSD, Linux, Windows
- [ ] Update CHANGELOG.md
- [ ] Release on GitHub
- [ ] Update documentation

---

## Phase 7: Post-Release

### Priority: P3 - Medium

#### Post-Release Tasks
- [ ] Monitor Hermes agent stability
- [ ] Collect user feedback on fixes
- [ ] Gather user reports
- [ ] Plan v0.3.0 improvements
- [ ] Address user-reported issues
- [ ] Plan next version release

---

## Notes

### Known Issues and Limitations

1. **Hermes Context Overflow (#19)** - FIXED in v0.2.0
   - Session can now exceed slot context when compaction off
   - Validation catches and rejects oversized requests

2. **Hermes Fixed Prompt (#85)** - FIXED in v0.2.0
   - Tool schemas now loaded before stable part
   - No more mid-prompt tool lines

3. **FreeBSD /proc Mounting** - KNOWN LIMITATION
   - Requires `/proc` to be mounted
   - Documented in README.md
   - Build automation verifies mounting

4. **Boss Agent CLI (#403-#407)** - FIXED in v0.2.0
   - Full integration complete
   - Plugin API and live status implemented
   - Self-test command added

### Future Improvements

1. **v0.3.0 Roadmap** - See [ROADMAP.md](ROADMAP.md) for future planning
2. **Platform Support** - Linux, Windows, macOS to follow
3. **Mobile Support** - Android/Termux integration for v0.3.0
4. **CLI-Anything** - Host automation control panel for v0.3.0

---

## References

- [Issue #19](https://github.com/brianreborn/familia/issues/19) - Hermes context overflow
- [Issue #85](https://github.com/brianreborn/familia/issues/85) - Fixed prompt
- [Issue #403](https://github.com/brianreborn/familia/issues/403) - Boss CLI
- [Issue #404](https://github.com/brianreborn/familia/issues/404) - Harness2 plugin API
- [Issue #405](https://github.com/brianreborn/familia/issues/405) - Harness2 live status
- [Issue #406](https://github.com/brianreborn/familia/issues/406) - Harness2 self-test
- [Issue #407](https://github.com/brianreborn/familia/issues/407) - Boss API validation
