# MELTY-style Crossover Mod Platform — PRD

## Original problem (pivoted 2026-10-19)
Initially: AI browser-game generator from blended game references (Kimi K3). The user then pivoted: build an AI-assisted **Windows game-modding & mashup platform** with web catalog, desktop companion/installer, reusable game adapters and a Kimi K3 coding workflow; prove one real crossover on installed games (install, gameplay test, rollback) before expanding. Browser generator removed by user request. Also requested: Claude, ChatGPT, Gemini, ElevenLabs integrations.

## User choices
- Kimi K3 primary via Hugging Face Inference Providers (HF_TOKEN, model moonshotai/Kimi-K3, router.huggingface.co/v1; Moonshot key removed); fallback chain Claude Sonnet 4.6 / GPT-5.2 / Gemini 3.1 Pro via Emergent key; model picker in the top bar
- Single user, no login. Companion = Python (stdlib) app; approved operation types auto-run (toggle per op)
- Latest requested host: **Call of Duty: WWII single-player campaign**. After being told no compatible campaign loader was verified, user approved **Fix detection and campaign status**, not a working mod loader. Preserve WWII as intended host without substituting another game. Earlier Cold War host assessment remains implemented; neither game currently supports MELTY mod loading.
- Approved scope: **Phase 1 only**, metadata-only compatibility assessment; no working Cold War loader promised, no game modification or new credentials/services authorized.
- ElevenLabs: SFX generator built, disabled until ELEVENLABS_API_KEY is set
- $9/day enforced ceiling (configurable), per-run ceiling $2.50

## Architecture
- Backend FastAPI: server.py (mods, budget, providers, assets, sfx), devices.py (pairing, device tokens hashed, restricted job queue, companion API), packages.py (meltpack/1 releases, BepInEx checksum pinning, catalog, compat matrix, install/restore, export zip), modagent.py (Kimi tool loop: files, adapter docs, game info, build, test_in_game, knowledge notes, finish; bounded 18 turns/5 builds/3 tests), adapters.py (seeded adapters + knowledge notes), budget.py (atomic Mongo reservations), llm.py (provider chain + cost accounting), sfx.py
- Companion: backend/companion/melty_companion.py — detect games (Steam/Epic/GOG/folders, Unity mono/il2cpp/Unreal, Unity version, build id), dotnet build with locked csproj (blocks Exec/Target/Import), test_mod (journaled dev install → launch → BepInEx log MELTY_READY/MELTY_CHECK → screenshot → stop → restore), install/uninstall with journal + backups + conflict detection, launch/stop, logs, screenshot
- Frontend React: Discover, My mods, Create, Studio (design spec, versions, releases, build&test log w/ evidence, code editor, chat), Release (compat table, manifest, publish, install), My PC, Adapters, Assets, Budget

## Implemented & verified (2026-10-19)
- Backend 17/17 pytest; frontend flows tested by testing agent
- Simulated Linux companion verified: pairing, detection of fake Unity game, real BepInEx download + checksum, journaled install (23 files), conflict detection, restore of replaced original file, rollback on failed install
- AI agent loop verified end-to-end with Claude fallback (Kimi call fails with $0 balance and is recorded at $0)
- NOT verified (needs Windows + real games): dotnet build of BepInEx mods, in-game launch/test, screenshots, Steam launch behavior

## Backlog (latest approval takes priority)
- P0 verification: user updates paired companion to **0.3.1**, selects Rescan now in My PC, and checks WWII campaign Found/Not found/Unknown. Current read-time correction suppresses old DLogUploader selection but does not invent campaign-file presence. No WWII loader/build/gameplay test is authorized or implemented. Earlier Cold War actual-Windows version-resource verification is also pending.
- CONDITIONAL Phase 2 (not approved/not promised): only consider a small local gameplay change inside Cold War after a documented authorized loading route and compatibility with a specific legitimate build are established. Explicit separate approval required before game changes. Restoration only covers MELTY-managed modifications, not account penalties or online progression.
- CONDITIONAL Phase 3 (not approved/not promised): first real Cold War-host crossover, describe/build/run/review/restore, only after Phase 2 is genuinely supported. No arbitrary copyrighted asset or entire engine transfer promises.
- Deferred P1: BepInEx 6 / IL2CPP adapter; shared-dependency reference counting for loader uninstall; packaged .exe companion. Screenshot-to-AI vision is already implemented (not backlog).
- Deferred P2: multiplayer sync/session service; simultaneous cross-engine runtime bridge/compositor; release review/signing. Neither multiplayer nor cross-engine operation is promised in this phase.
- Refactoring: adapter/companion modularization only if support expands; not necessary for this delivered phase.

## 2026-10-19 update
- Auto game detection: companion scans on pair/start + every 30 min (Steam/Epic/GOG/registry uninstall entries filtered by engine/launcher folders on all drives); Create uses clickable game cards
- Kimi K3 switched to Hugging Face router — verified tool calling + multi-turn reasoning
- Game details: hover card (version, engine, Unity, loader, adapter) + ⓘ drawer (adapter doc, knowledge notes, mods using it); also from My PC games table
- First real crossover on Windows: still pending — requires user to pair their PC
- Mashup Ideas page (/ideas): free moddability ranking of detected pairs + optional Kimi K3 pitches (~$0.004 actual), "Use this pair" prefills Create
- First-crossover live checklist on My PC (11 steps, live)
- Screenshot review: after each in-game test the screenshot (shrunk to 1280x720 JPEG) is sent to Kimi K3 (vision via HF); AI must answer VISUAL_REVIEW ok|issues and fix code-caused problems; stored in verification.visual_review, shown in Studio + activity log thumbnails. Backup models get text only.
- 2026-10-19: Hosting is toolchain-based: BepInEx5 C# (Unity Mono), UE4SS Lua (Unreal 4/5), UnrealScript via official SDK (Killing Floor 2). Non-hostable games show specific reasons (IL2CPP, RE Engine/Game Pass, unknown engine); anti-cheat online games (CoD etc.) blocked deliberately. Launcher/service entries filtered. Companion 0.2.0: UE3/RE detection, self-update, MELTY-Setup.bat one-click installer (winget Python/.NET, desktop shortcut). Tested iteration_2/3 (20/20).

## Cold War Phase 1 delivered — 2026-10-19 (workspace date)
### Approved requirements and limits
- Cold War stays the explicitly intended host, even though hosting is unavailable. Exact status: **Not supported by MELTY — host compatibility unverified**.
- Clearly separate detected installation, documented unofficial community scripting, and actual MELTY loader support (false). A Unity/Unreal detection or script revision must never imply Cold War support.
- Atian Tools documents T9 script revisions 37/38, not matching retail versions or an authorized loader: https://github.com/ate47/atian-cod-tools
- Activision policy covers unauthorized game-modifying software/injectors: https://support.activision.com/articles/call-of-duty-security-and-enforcement-policy . No general private-match exemption or authorized retail loading route was established. No ban-safety guarantee. Unsupported kernel-protection claims removed from generic blocked adapter wording.
- No compiler, injector, third-party loader, new AI service, binary upload, memory access, executable patch or game-file write in Phase 1.

### Implementation
- adapters.py: Cold War matcher precedes broad Call of Duty and generic engine matches. Identifies specific names, executable and Steam appid; unrelated 2005 game named Cold War is not treated as T9. Runtime read overlays correct stale stored hostability and engine labels.
- devices.py: GET /api/games/cold-war/compatibility, PATCH /api/games/cold-war/version, POST /api/games/cold-war/check. Saved reports include observed store/source/path/executable metadata and Unknown values, separate user-reported version, check timestamp, sources/prerequisites. Manual version validates length and Unicode controls. Inspection uses existing approved inspect_game operation; online companion >=0.3.0 required. Partial/older results cannot erase earlier metadata.
- Companion 0.3.0: metadata-only Cold War inspection via Windows version resource APIs; no execution/injection/download/upload. Detects Cold War before engine file-content scans. Local refusal of Cold War build/test/install/launch, independent of server toolchain claims. User-Agent preserved. Updating the existing companion uses a plain script download, not compiler setup.
- Server/agent/packages: reject Cold War paid generation, chat, build, release creation/publishing/install/export and project SFX before expenditure/work; direct jobs and pre-existing queued jobs guarded too. Restoration remains available. Supported adapters unchanged.
- UI: ColdWarCompatibility panel in My PC drawer/Create; intended host survives query navigation and refresh and includes correct device_id. Metadata-check progress, approval/offline/version/errors/success, manual version editing, source links, disabled actions with adjacent reasons. Successful check refresh race fixed. Cold War not suggested as secondary/inspiration; prefilled secondary choice shows clear stopping point. Legacy Studio/Release controls disabled; Create cannot become enabled while library identity is loading.
- Responsive navigation, device-card and Ideas rows fixed at mobile/tablet; game-card hover no longer intercepts adjacent cards or remains over selected cards. Info icon no longer overlaps status/version text.
- No new auth, accounts, external services, or credentials. Existing personal single-user pairing architecture retained.

### Final validation
- /app/test_reports/iteration_6.json: **78/78 passed** (76 Cold War API/companion regressions + 2 transient-device cleanup tests); all requested browser checks passed; frontend compiled successfully, no page errors.
- Iterations 4/5 issues fixed and retested: completion display, metadata retention, aliases, Unicode, SFX legacy record error, secondary suggestions, mobile overflow, hover overlap.
- Windows version.dll calls were **MOCKED in tests**, using simulated installations. Real Windows executable metadata reading remains USER VERIFICATION PENDING. No real Cold War loader/build/in-game session was tested or implemented.
- No paid AI calls during tests; transient devices/jobs/games/mods/releases/tokens cleaned. The user's ATLAS device was never commanded/modified by testing. It may independently rescan while running; do not mistake that activity for test changes.
- Test files: backend/tests/test_cold_war_compat.py, test_cold_war_companion.py, test_cold_war_iter5.py; cw_ui_fixture.py for isolated browser fixtures. Old SIM-bound tests skip when historical fixtures are absent. Test credential lifecycle in memory/test_credentials.md.
- Current stopping point: read-only compatibility check ready, **Cold War hosting still unavailable**. No further adapter phase authorized.


## WWII campaign detection/status fix — 2026-10-19 (workspace date)
- User request: “we need to unblock Call of duty WWII”; chose **Single-player campaign**, then explicitly approved **Fix detection and campaign status** after the lack of a verified campaign loader was explained. Do not claim this unblocks hosting.
- Reproduced actual scanner bug using read-only API: Steam appid 476600, library build 22081346, generic blocked-anticheat adapter, unknown engine, helper DLogUploader.exe selected instead of campaign executable. No game command was sent to user PC.
- Feasibility: campaign binary s2_sp64_ship.exe (https://steamdb.info/depot/476601/); MP binary s2_mp64_ship.exe is separate. https://github.com/Rattpak/S2MP-Mod documents Multiplayer/Zombies rather than campaign; https://github.com/Brentdevent/S2x describes unfinished modding support. GSC compiler support alone is not a loading route. No verified compatible campaign loader for the user's build established.
- Companion **0.3.1**: is_wwii + wwii_metadata recognize title aliases/appid/known executable; explicit directory-only metadata detection of campaign and MP files; helper never chosen, MP never substituted for missing campaign. Missing file => Not found; uninspected/unreadable => Unknown. Case insensitive; executable-named directories not proof of presence. No game-content reads, binaries executed, file writes or external installs. Generic fallback excludes DLogUploader.exe.
- New cod-wwii-s2 adapter precedes blanket CoD/engine matching. Status: **Not supported by MELTY — WWII campaign loader compatibility unverified**. Runtime unverified_host_status corrects old stored engine/hostable/helper-exe values without falsely claiming the campaign file was observed. Fresh companion scans persist campaign_exe, multiplayer_exe, campaign_executable_found and wwii_mode.
- Shared reject_unverified_host guard (formerly reject_cold_war) now covers WWII and Cold War, including legacy projects/releases and stale queued jobs. Backend create also rejects these titles as secondaries before budget/generation, matching the frontend. Local companion independently refuses unsupported build/test/install/launch. Restore/support for other game engines unchanged.
- UI: WWII-specific drawer/status panel and host-picker entry; actual campaign file status distinct from expected filename, multiplayer file and Steam build shown separately. Evidence links, update/rescan instructions, disabled mod controls with reasons. Intended WWII host retained in URL/device selection; no alternate game or borrowed-source suggestion. Old online-game/borrow-only labels no longer shown for WWII.
- My PC update downloads plain companion script, preserves pairing, no compiler setup. User should close current companion, replace script with 0.3.1, restart and Rescan now. Until then observed campaign file is Unknown. Real Windows rescan remains USER VERIFICATION PENDING.
- Tests: iteration7 frontend passed (390/768 layouts, statuses, alias/deep-link loading states, disabled actions, supported-game controls); build compiled. iteration8 final backend **113/113 passed**: 37 WWII regressions + 76 Cold War. Twenty obsolete SIM-specific cases skipped because fixture absent. Tests used MOCKED local installations/Windows conditions; no real game/mod launch or AI spend. Added test_wwii_detection.py and wwii_ui_fixture.py; only current companion-version assertions updated in earlier suites.
- All this phase's temporary fixtures/tokens removed. Older cancelled orphan jobs and expired pairing rows noted by testing were pre-existing, not modified (unrelated to approved scope). No functional issues outstanding in this fix. Further WWII loader work remains conditional on a verified route and separate user approval; multiplayer/cross-engine features remain deferred.

## 2026-06 Companion update fix
- Window closed instantly: user double-clicked bare melty_companion.py (no args). Now: no-args + paired = run; unpaired waits for Enter.
- New GET /api/companion-app/update.bat?server= (MELTY-Update.bat): downloads latest into %USERPROFILE%\MeltyCompanion, refreshes desktop shortcut, runs companion, pauses.
- self_update uses subprocess.call instead of os.execv (Windows console stayed detached). VERSION 0.3.2.

## 2026-06 Fallback models updated
- Chain: Kimi K3 (HF) -> Claude Sonnet 5.5 (claude-sonnet-5-5, Emergent key) -> GPT-6.1 Sol (gpt-6.1-sol, user OPENAI_API_KEY, Responses API adapter since chat/completions rejects tools+reasoning) -> Gemini 4 Argon (gemini-4-argon, user GOOGLE_API_KEY via OpenAI-compatible endpoint; key NOT provided yet = disabled).
- llm.py: DIRECT providers dict, _call_direct/_call_openai. Prices $2/$10 per M for all three.


## 2026-10-19 — Three-tab simplification + honest "done"
- UI is exactly 3 tabs: Copilot (/, /mods/:id), Game Selector (/games), Trainer (/trainer). Everything else sits behind the gear menu (History, Settings & AI budget incl. model picker, PC connection & permissions, Game files workshop, Uploaded files, Compatibility notes, Ideas, Community mods). /new redirects to /. Studio/NewMod/ChatPanel removed.
- Copilot: mod rail (+ mobile strip), composer (pick game, optional mix-in game, describe), chat with plain progress checkmarks (Plan / Game files / Write / Build / Try in game), inline approvals (Allow / Not now), Install & play / Check it worked / Remove from game, queue while busy + Stop ("Stopping…"), technical details (work log, design, code, versions, releases) in a side sheet. Drafts persist in localStorage.
- Honest verification: finish tool requires feature_checks; a mod is "verified" only when every feature check PASSes in the game's own log (auto test or user playtest via POST /api/mods/{id}/confirm). Prompt rules: no PASS for "loaded/waiting/menu"; UE shipping builds strip DrawDebug* → use HUD ReceiveDrawHUD; aim via SetControlRotation with read-back. Later failed checks downgrade verified → built.
- New backend playtest.py: GET/POST /api/mods/{id}/play, POST /confirm (collect_logs → feature results, plain chat message, old-companion notice), POST /remove.
- Companion 0.5.1: collect_logs reads UE4SS.log + CET mod logs, keeps last result per check after the latest MELTY_READY.
- Trainer fixes: non-dict/unknown keys → 400, ms-strictly-increasing rev, presets per device, time_of_day default 12, "Install First" status, Restore only when installed, device pinned (ws-device) and ?game= deep link.
- Launchers (Epic Games Launcher, Unreal Engine) filtered out of game lists.
- RoN × STALKER 2 mod status corrected to "Ready to try"; rebuild of aim assist (HUD marker + real view turn) queued on ATLAS (generation 0d1b202bf2944919baa46ffd5a7daa60).
- Tested: iteration_11 (backend 38+ pass, frontend flows verified); all reported issues fixed afterwards.

## Next
- P0: user updates ATLAS companion (0.3.2 → 0.5.1) so "Check it worked" can read game logs; play a mission with the rebuilt aim assist and confirm.
- P1: automatic repair loop from confirm results ("fix it" uses last_confirm log); STALKER 2 + RoN asset extraction crossover.

## 2026-10-19 — Code audit fixes (MELTY_code_audit.md)
- Mix-in (source) games no longer go through host checks when creating a mod (server.py create_mod).
- Manual build now sends the game's toolchain + adapter params (tc_params) and only records the build if files didn't change meanwhile.
- Builds are tied to a files hash: tests refuse stale builds, finalize marks stale builds "unbuilt", verification only counts if it tested the current build; releases refuse a build whose hash doesn't match.
- Explicit stages shown in Copilot header: Built → Installed → Loaded in game → Confirmed (GET /api/mods/{id}/play returns stage).
- Already addressed before the audit (audit zip was older): Install & play / Check it worked / Remove buttons, Cyberpunk CET/REDmod adapter, asset extraction, trainer.
- Still open: real in-game acceptance on the user's PC (needs companion 0.5.1 + a mission playthrough).
