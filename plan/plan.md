# Cold War as a MELTY Host: Compatibility First

Extend MELTY toward running crossover mods inside Black Ops Cold War itself, rather than using Cold War only as inspiration for another game.
The first release provides a truthful, read-only compatibility assessment; it does not promise or enable a working Cold War mod loader.

## Who it's for

The existing MELTY user who owns Black Ops Cold War on Windows and wants Cold War to be the game in which the crossover runs.

## Core features and experience

- Preserve the explicit choice of Cold War as the intended host. Do not silently substitute another game or an inspiration-only crossover.
- Give Cold War a specific compatibility explanation instead of relying solely on the existing blanket Call of Duty restriction. This does not remove the restriction on installing or running unsupported mods.
- Separate three facts: the game is detected, community scripting tools exist, and MELTY can actually load a mod. Only the first two currently have supporting evidence.
- Show installation details available through non-invasive inspection, including the store and executable version when available. Missing information remains “Unknown,” never an assumed match.
- Show the current result as “Not supported by MELTY — host compatibility unverified,” with the missing prerequisites and supporting sources.
- Keep Cold War build, install, and mod-launch actions unavailable while there is no verified loading route. Do not spend AI credits generating a supposedly runnable Cold War package in this state.
- Keep the existing supported-game experience unchanged.

### Evidence and limits

The current app has no Cold War-specific working host adapter. Its Call of Duty name rule blocks hosting; broader Unity or Unreal detection does not establish Cold War compatibility. The existing kernel-anti-cheat explanation is not evidence of Cold War's particular protection technology and must not be repeated as a verified fact.

[Atian Tools](https://github.com/ate47/atian-cod-tools) documents unofficial Cold War/T9 scripting capabilities, including compiler support for script revisions 37 and 38. Those revisions are not proof of compatibility with the user's installed retail build, nor proof of an authorized loading route.

[Activision's enforcement policy](https://support.activision.com/articles/call-of-duty-security-and-enforcement-policy) covers unauthorized game-modifying software and injectors. No general exemption for private matches was established by the reviewed sources. No authorized retail Cold War loading route was established either. “Unofficial tools exist” must not be presented as “safe, supported hosting is ready.”

## User flow

1. Open the existing PC game library and select Black Ops Cold War.
2. See Cold War retained as the desired host, alongside its actual support status.
3. Use a read-only compatibility check to display available installation and version information. Enter the displayed game version manually if it cannot be read automatically.
4. Review the result: what is known, what remains unverified, and why a runnable crossover cannot currently be offered.
5. Remain at this clear stopping point unless a later, separately approved host integration becomes feasible. The check never installs third-party mod tools or changes the game.

## UI/UX feel

Preserve MELTY's existing visual style and navigation. Use plain-language status labels with text explanations, not color alone. Keep “Detected,” “Unverified,” and “Supported” visibly distinct. Explain disabled actions beside the controls, without implying that accepting a warning would unlock compatibility.

## Implementation phases

### Phase 1 — MVP: Cold War compatibility clarity

Build only the Cold War-specific status, read-only installation assessment, evidence-backed explanation, and safeguards against unsupported build or installation actions. The delivered outcome is an honest answer about the user's installation and MELTY's current limitations, not a working crossover.

No compiler, injector, third-party loader, new AI integration, binary upload, or game-file modification is included in this phase.

### Phase 2 — Conditional: first mod running inside Cold War

Proceed only if a documented, authorized loading route and compatibility with a specific legitimate game build can be established. Scope the first integration to one small local gameplay change, with explicit user approval before game changes and restoration of MELTY-managed modifications.

This phase is not included in the MVP or guaranteed to become feasible. Private play alone is not sufficient evidence of authorization or account safety. Anti-cheat evasion, DRM bypass, and progression or unlock manipulation are excluded.

### Phase 3 — Conditional: the first real crossover session

If Cold War hosting becomes genuinely supported, extend the existing describe–build–run–review–restore experience to a user-selected secondary game's gameplay idea. Keep the crossover inside Cold War and disclose the supported mechanics and limitations. Do not imply that arbitrary copyrighted assets or entire game engines can be transferred.

Multiplayer synchronization and simultaneous cross-engine operation remain deferred; neither is promised by this proposal.

## Assumptions

- The user wants Cold War itself as the host, as explicitly selected, not a substitute game.
- The user owns a legitimate Windows copy. Store, version, and intended mode are not assumed to be known.
- Approval authorizes Phase 1 only. It does not authorize game modification, third-party tool installation, or account-risking actions.
- Existing PC pairing remains the connection method; no new accounts, credentials, or paid services are needed for this MVP.
- Compatibility inspection uses installation metadata only, without process-memory access, executable patching, or uploading proprietary game files.
- The first phase may conclude that hosting remains unavailable. It is not a promise to unlock Cold War.
- Future restoration concerns changes made by MELTY; it cannot reverse account penalties or guarantee restoration of online progression.
