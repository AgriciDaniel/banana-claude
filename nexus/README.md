# NEXUS

A gesture-driven spatial computing environment for the browser, with a
conversational AI resident inside it.

Ten holographic modules orbit the viewer inside a volumetric room with no
walls. You rotate the ring, grab cards, throw them, expand them and freeze the
world **with your hands** - tracked on-device, at 60 fps, with no video ever
leaving the browser. Mouse and keyboard exist as a complete fallback, not as an
afterthought.

Phase 4 made it cinematic: six worlds the room morphs between, transitions with
camera choreography, a floor that becomes a trading surface, light that trails
your hands, glass that ripples when touched, and two-handed gestures.

Phase 3 made every module real: live weather that changes the room's actual
weather, a live portfolio, live fixtures, live headlines with an AI digest, and
diagnostics measured off this machine.

Phase 2 added the assistant: say **"Nexus"** or draw a circle in the air, and it
wakes. It hears you, answers out loud while the words assemble from particles in
mid-air, and drives the interface through the same API your hands do. Cut it off
mid-sentence and it stops immediately.

Nothing on a card is a placeholder any more.

---

## Run it

```bash
npm install
```

```bash
npm run dev
```

`npm install` runs `scripts/setup-assets.mjs`, which vendors the MediaPipe WASM
runtime out of `node_modules` and downloads the 7.8 MB hand-landmark model into
`public/`. That makes tracking work offline and keeps a third-party CDN off the
critical path. If either step fails the app falls back to the CDN at runtime -
it degrades, it does not break.

Open http://localhost:3000 and choose **Enter with hands** (grants camera) or
**Use pointer**.

---

## Interaction

### Hands

| Gesture | Action |
|---|---|
| Swipe left / right | Rotate the ring one slot, with momentum |
| Pinch | Grab the card you are pointing at |
| Release pinch | Drop it - a fast release throws it under physics |
| Pull toward you | Expand the focused card |
| Push away | Collapse it |
| Open palm, held still | Freeze the world |
| Circle | Recognised and reserved for the phase-two AI surface |

### Pointer and keyboard

Everything above has an equivalent, so the OS is fully operable without a
camera - and by anyone who cannot comfortably hold a hand in the air.

| Input | Action |
|---|---|
| Left / Right arrows | Rotate the ring |
| Drag background | Free-spin the ring, releases to the nearest slot |
| Scroll | Rotate one slot |
| Hover / click / double-click a card | Hover, grab, expand |
| `Space` / Up | Expand or collapse the focused module |
| `Esc` / Down | Collapse, then deselect |
| `Enter` | Select |
| `1`-`9`, `0` | Jump to a module |
| `F` | Freeze the world |
| `H` | Hide the HUD |
| `D` | Diagnostics - draws the raw hand skeleton |
| `M` | Mute |

---

## Language

English and French, switchable live from the boot screen or the status panel.
The choice persists to `localStorage`; a first visit follows
`navigator.languages`.

Switching relabels the HUD, the log, the module descriptors **and repaints the
3D card textures**, which are canvas-painted per locale and cached.

`<html translate="no">` is set deliberately. Chrome's auto-translate was
rewriting the interface on top of the real translations - it renamed the
product from *NEXUS* to *LIEN* and turned the input readout *POINTER* into
*AIGUILLE* (a clock hand). Machine translation cannot know these are instrument
labels, so it is declined and a real language switch is offered instead.

Adding a locale means adding a catalogue in `src/i18n/`. The French catalogue is
typed `Record<TranslationKey, string>`, so a missing string is a build error
rather than a stray English word in a shipped UI.

---

## Architecture

Layered, with one rule: **a layer may depend on the ones below it, never
sideways.** The gesture engine does not know what a card is; cards do not know
what a pinch is. `scene/InteractionDriver.tsx` is the only seam between them,
which is what will let phase two add voice or gaze without touching either side.

```
src/
├─ config/      Design tokens, module registry, quality ladder
├─ core/        Math, capability detection, event bus, shared types
├─ animation/   Spring integrators and the motion vocabulary
├─ gesture/     MediaPipe lifecycle, filters, detectors, engine
├─ physics/     Rapier debris field
├─ rendering/   Canvas, camera rig, post pipeline, quality governor, environment
├─ scene/       Ring geometry, cards, reticle, interaction driver
├─ audio/       Procedural WebAudio engine
├─ hud/         DOM interface
├─ hooks/       Input lifecycles, telemetry sampler
├─ i18n/        Catalogues, locale store, translator
├─ shaders/     GLSL
└─ stores/      Zustand (discrete) + runtime bus (continuous)
```

### State is split by frequency, not by feature

This is the decision the whole app hangs on.

- **Zustand stores** hold *discrete* state - which card is expanded, the
  tracking status, the quality tier. Things that change on user intent.
- **`stores/runtime.ts`** is a plain mutable object holding *continuous* state -
  ring angle, hand positions, frame timings. The render loop reads and writes it
  at up to 120 Hz.
- **`hooks/useTelemetry.ts`** samples the runtime into a valtio proxy at 10 Hz.

The consequence: a 120 fps scene renders **zero** React trees per frame. Putting
the ring angle in React state would re-render ten cards sixty times a second to
move a number the HUD only reads ten times a second.

### Motion

There is no linear interpolation in any user-visible motion. Every value that
moves - position, rotation, scale, glow, ring angle - is integrated through a
damped harmonic oscillator in `animation/Spring.ts`. Overshoot, momentum and
elasticity are properties of the integrator, not keyframes bolted on afterwards.

Card states differ by *spring config*, not by curve: dragging uses `lag` (heavy,
trailing), expanding uses `bouncy`, hovering uses `crisp`. That is why each
state has a recognisably different signature.

The ring is a single `AngularSpring` whose target is always a slot centre, so
snapping, momentum and stacked swipes fall out of one integrator instead of
three systems fighting each other.

Four animation libraries, each with a real job and no overlap:

- **Custom springs** - anything physically coupled (cards, ring, camera drift).
- **React Spring** - the reticle. A UI affordance, not a physical object.
- **GSAP** - the boot title stagger and camera dollies. Authored, not simulated.
- **Framer Motion** - DOM panels and presence transitions.

### Gesture pipeline

```
camera -> HandLandmarker -> One Euro filter -> HandFrame -> detectors -> events -> bus
```

- **One Euro filtering** adapts its cutoff to speed: heavy smoothing at rest
  (kills tremor), light smoothing in motion (keeps swipes crisp). Single biggest
  quality lever in the pipeline.
- **Every measurement is normalised by hand span**, so gestures work at any
  distance from the camera.
- **Depth comes from apparent hand size**, not landmark `z`, which is noisy and
  only weakly metric. The baseline freezes mid-stroke so a slow pull cannot be
  absorbed by its own drift.
- **Detectors are Schmitt triggers with cooldowns.** Pinch enters at 0.66 and
  exits at 0.42 - a single threshold chatters at the boundary and reads as
  broken tracking rather than as a physical grip.
- **Two preallocated hand slots.** The hot path allocates nothing, so tracking
  never causes a GC hitch mid-gesture.
- Inference is skipped when the camera has not produced a new frame, roughly
  halving the cost on a 30 fps webcam.

### Rendering

- Atmosphere, particles, beams and grid are procedural GLSL. No textures, no
  HDRI, no external assets.
- Reflections come from an environment rendered out of in-scene `Lightformer`s,
  so the glass reflects the same key light the scene is actually lit by - and
  nothing is fetched.
- Cards use three.js's built-in `transmission`, which shares one render pass
  across all ten. drei's `MeshTransmissionMaterial` would have cost one pass
  *per card*. The pass runs at half resolution.
- Card faces are painted to canvas textures rather than drawn as DOM overlays,
  so they refract and bloom with the glass they sit behind.
- Every shader reads `interaction.sceneTime`, never its own clock, so a freeze
  slows the entire world coherently instead of per-material.

### Performance

`rendering/AdaptiveQuality.tsx` walks the quality ladder in `config/quality.ts`.

- Asymmetric hysteresis: dropping needs 1.5 s of sustained pain, climbing needs
  6 s of headroom.
- A cooldown after every change, because the frame right after a tier switch is
  always slow (shader recompiles).
- **A one-way ratchet.** A tier that has already failed is never auto-entered
  again. Without it the governor oscillates forever: HIGH runs at 90 fps so it
  climbs to ULTRA, which runs at 33, so it drops back to HIGH... The GPU is not
  going to get faster during the session, so the first failure is the answer.

Renderer stats are read with `gl.info.autoReset = false` and reset once per
frame - the post pipeline issues several `gl.render()` calls and each one resets
the counters, so the naive reading reports one draw call.

### Audio

Every sound is synthesised at runtime. There is not a single audio asset in the
bundle: an ambient pad of stacked fifths, a sub drone, a filtered-noise air
layer, a generated convolution reverb, and a UI voice set drawn from the same
harmonic material so it never fights the bed.

---

## Graceful degradation

| Condition | Behaviour |
|---|---|
| No WebGL | Full DOM fallback rendering the same module registry |
| Camera denied or absent | Pointer + keyboard, banner explains, everything still works |
| GPU delegate unavailable | MediaPipe falls back to the CPU delegate |
| Weak GPU | Quality ladder drops tiers and holds |
| `prefers-reduced-motion` | Camera drift and chromatic aberration reduced |
| Offline | Tracking assets served from `public/` |

---

## Status

Verified in-browser against live APIs: production build, type-check, all six
worlds morphing, module-claimed environments and their hand-back on collapse,
the market floor tracking real day changes, gesture trails, card ripples, the 3D
charts, all ten expanded panels, both locales, and the full assistant loop
answering from live module readings.

Frame rate on Intel integrated graphics: 96-102 fps in the worlds, 62 fps with
Stocks expanded and the market floor running.

**One performance trap worth knowing about.** Card faces are painted canvas
textures, repainted whenever a displayed value changes. The Music module's level
changes twenty times a second, which was re-rasterising a 640x888 canvas and
re-uploading a texture at that rate — on its own enough to take the environment
from 145 fps to 12. Volatile readings are now quantised to a step the eye cannot
resolve; the expanded panel still shows the unrounded value.

**Hand tracking has still not been exercised against a live camera**, and that
now includes the two-handed gestures. The pipeline is complete and the geometry
is straightforward, but the thresholds in `twoHand.ts` are reasoned rather than
tuned. Press `D` for the raw skeleton while adjusting them.

**Barge-in leaks occasionally on loudspeakers.** Headphones remove it.

**Sports data is thin on the shared test key.** `NEXUS_SPORTSDB_KEY` fixes it.

**Projects ship with no media.** The manifest supports images and video; this
build has none to show, so those grids are empty rather than filled with
invented screenshots.

## Next

The module contract is `src/config/modules.ts`. Adding a real feature means
mounting it against an existing id - the scene, the gesture engine and the
physics layer do not change.

---

## The assistant

Add a key and restart:

```bash
cp .env.example .env.local
```

Put a [Gemini API key](https://aistudio.google.com/apikey) in `GEMINI_API_KEY`.
Without one, everything else still runs and the assistant reports itself
**offline** rather than failing on your first sentence.

### Waking it

| Trigger | Notes |
|---|---|
| Say "Nexus" | Recognised mid-sentence: "Nexus, open stocks" is one breath, and the tail becomes the command |
| Draw a circle in the air | Phase 1's reserved gesture, claimed by subscribing to the existing gesture bus |
| Press `N` | For anyone with no microphone and no camera |

Waking sends a wavefront out through the room, ripples the floor, and leaves the
whole interface sitting fractionally brighter for as long as it is listening.
`Esc` silences it mid-sentence; a second `Esc` dismisses it.

### Talking to it

Ask it things — "how is Nvidia today", "summarise the latest AI news", "explain
MCP" — or tell it what to do: "open stocks", "rotate left", "show my calendar",
"close that", "freeze", "passe en français". Commands and questions can be the
same sentence: *"open stocks, then tell me how Nvidia is doing"* expands the
module and answers, in that order.

**"Explain this"** works, because the currently expanded module is injected into
the prompt on every turn.

There is also a text field in the assistant panel. It is not a lesser path:
speech recognition is missing entirely in several browsers, unusable in a noisy
room, and not everyone can comfortably talk to their computer.

### How it is wired

```
speech  ──> SpeechRecognizer ──┐
                               ├─> AssistantEngine ──> /api/gemini ──> Gemini
typing  ──> AssistantPanel ────┘         │                              (SSE)
                                         ├─> commands  ──> ring / cards / freeze
                                         ├─> HoloText  ──> particles in space
                                         └─> Speaker   ──> /api/tts ──> spatial voice
```

`scene/InteractionDriver.tsx` and `ai/commands.ts` are the only seams between
the assistant and Phase 1. The gesture engine does not know the assistant
exists; the assistant does not know what a pinch is.

**Commands run through the public API.** `open_module` calls the same
`ring.focus` and `useCarouselStore.expand` a pinch does. There is no privileged
path for the AI, which is why "open Instagram" and a hand gesture produce
identical motion — they are not two implementations of one idea, they are one.

**The tool loop is server-side.** A model that calls a function stops and waits
for the result; if nobody sends one, the turn ends silently. The route streams
the call to the browser (which performs it against the live scene immediately),
synthesises the tool response, and continues the same turn on a second upstream
request. The user sees one continuous reply and the interface has already moved.

**Everything streams.** Tokens arrive by SSE, the text re-lays out at reading
speed, and each finished sentence is queued for speech while the model is still
generating the next — so it starts talking before it has finished thinking.

**Interruption is instant.** Speaking while it speaks aborts the fetch, drops
the audio queue and silences playback in the same tick. The hard part is that
the microphone also hears the loudspeaker: transcripts are matched against
five-character stems of what is currently being said, and the check stays armed
for 1.4 s after playback ends, because recognition lags the speaker. Headphones
remove the problem entirely.

### Holographic text

Replies are rasterised to an offscreen canvas, the lit pixels become particle
targets, and a fixed pool flies onto them in reading order. Two details carry it:

- **Raster resolution is chosen to match the particle budget.** Rasterise too
  finely and the sampler backs off to a step wider than the glyph strokes, and
  the result is a faint dotted smudge rather than text.
- **Particle size is derived from world units and the sampling density**, not a
  constant, so strokes stay continuous at any distance or text length.

### Voice

| Backend | Quality | Time to first audio | Spatial |
|---|---|---|---|
| Gemini TTS (default) | High | ~2.3 s fixed overhead | Yes — panned from the centre of the room |
| Browser SpeechSynthesis | Serviceable | ~0.2 s | No |

Gemini TTS returns raw PCM, which is decoded into Web Audio and played through a
`PannerNode` whose listener tracks the drifting camera. The browser's own
synthesiser writes straight to the output device and can never be spatialised —
it is the automatic fallback, and it takes over permanently if a TTS request
fails mid-conversation rather than leaving the assistant mute.

Measured on this machine: ~2.3 s of fixed overhead plus roughly realtime
generation. If you would rather have a faster, flatter voice, set `GEMINI_TTS=0`.

### Configuration

| Variable | Default | Effect |
|---|---|---|
| `GEMINI_API_KEY` | — | Required. Assistant is offline without it |
| `GEMINI_MODEL` | `gemini-3.7-flash` | Any streaming-capable Gemini model |
| `GEMINI_GROUNDING` | on | Google Search grounding, so live figures are real |
| `GEMINI_THINKING_BUDGET` | `0` | Raise to trade latency for depth |
| `GEMINI_TTS` | on | `0` forces the browser voice |
| `GEMINI_TTS_VOICE` | `Kore` | Prebuilt Gemini voice name |

### Development

`window.__nexus` exists in development builds: `wake()`, `sleep()`,
`ask(text)`, `run(command, args)`, `state()`, and `simulate(text, wps)` which
streams canned text through the full visual path with no API call — the
holographic text was tuned entirely through it.

---

## The modules

Every card is a live readout. The three numbers painted on a card face are
measurements, and each face carries the name of the source that produced them,
because a number with no stated origin is a number you cannot check.

| Module | Source | Needs a key |
|---|---|---|
| Weather | Open-Meteo | no |
| Stocks | Yahoo Finance | no |
| News | RSS + Gemini digest | Gemini for the digest only |
| Sports | TheSportsDB | no (shared test key) |
| Projects | `content/projects.json` + GitHub | no |
| System | Browser diagnostics | no |
| Music | Web Audio master bus | no |
| AI | Gemini | yes |
| Calendar | iCalendar feed | `NEXUS_ICS_URL` |
| Instagram | Instagram Graph API | Business account + token |

### Weather changes the room

This is the module that most obviously refuses to be a widget. Instead of a
cloud icon, the environment itself changes: real precipitation falls through
the volume, fog thickens, the light drains, and a thunderstorm throws real
light into the scene. If it is raining where you are, it is raining in here.

Every parameter — fall speed, wind drift, fog density, storm frequency — comes
from the live forecast for wherever the browser says you are.

### Stocks

Positions live in `src/config/portfolio.ts` (or `NEXUS_PORTFOLIO` as JSON),
because no public API knows how many shares you own or what you paid. Prices,
day changes, profit and loss, sector exposure and a month of history per holding
are all live. The 3D bars beside an expanded module are real position values.

### Projects

`content/projects.json` holds what only you know — descriptions, media, prompt
history. GitHub supplies what it knows: stars, forks, language, open issues and
last push, so a project's card ages by itself. Each project opens into its own
world with its media, its prompts and its live repository state.

### The assistant can see all of it

Every module's current reading is injected into the assistant's context on each
turn. Ask "what's the weather and how is my portfolio doing" and it answers from
the same numbers on the cards rather than searching the web and returning a
different figure. Modules that are not connected are described as not connected;
it will not invent a follower count.

### Two modules need credentials

**Calendar** wants `NEXUS_ICS_URL` — the secret iCal address your calendar
already publishes (Google: Settings, pick the calendar, "Secret address in iCal
format"). ICS rather than OAuth because a consent screen and a client secret is
a lot of ceremony for a single-user environment.

**Instagram** needs a Business or Creator account and a long-lived Graph API
token with `instagram_basic` and `instagram_manage_insights`. There is no
key-less tier and no way to infer any of it. The module is built in full against
the real API shape; without a token it reports `unconfigured` and says exactly
what is missing.

That state is deliberate and visually distinct from a failure. An honest "not
connected" is worth more than a convincing fake.

---

## Worlds

The room is not one place. Six environments, switchable from the rail on the
left, and the scene **morphs** between them rather than cutting.

| World | Character |
|---|---|
| Dark Lab | The default. Dark, blue, volumetric |
| Minimal Studio | Cold, clean, near-empty — the room as a photographic sweep |
| Glass Observatory | High and cathedral-like. Long shafts, thin air |
| Industrial Command | Warm and instrumented. The only world where amber is structural |
| Ocean Platform | Wide, low and slow. A horizon you cannot reach |
| Fog Chamber | Almost nothing is visible. Everything is felt at one metre |

An environment is **a set of numbers, not a scene**. Fog, grid, beams, motes,
lights and horizon all read their parameters from the active world, and
switching interpolates every one of them at once. Nothing is created or
destroyed, so a morph allocates nothing and never drops a frame. Adding a
seventh world is one entry in `src/config/environments.ts`.

### Modules can claim the world

Expanding a bound module pulls the environment with it and collapsing hands it
back. Stocks summons Industrial Command; Projects opens the Studio; Weather goes
out to the Ocean Platform; News rises into the Observatory. The mapping is data
(`MODULE_WORLDS`), so binding a future module to a world is a one-line change.

### Transitions are directed

A world change fires three things at once, all driven off a **single** number —
how far the world still has to travel:

- a pressure wave leaves the viewer and passes outward, tinted by the world
  being arrived at, with a matching ring crossing the floor;
- the camera pulls back and rolls slightly, then settles — the operator leaning
  away while the room rebuilds itself;
- the air turbulates, mote drift surging and decaying with the morph.

Sharing one progress value is why they stay in sync instead of each running its
own timer against its own easing.

### The floor becomes the market

Open Stocks and the ground stops being a neutral grid. Each lane carries one
real holding: colour is the day's direction, scroll speed is the size of the
move. A volatile morning is legible in peripheral vision without reading a
number. The data arrives as eight floats in a uniform, so the whole floor is one
quad.

---

## Micro-interactions

- **Motion leaves light.** Motes are emitted along the aim point's path, not at
  a single point per frame — sampling only at frame times leaves a dotted line
  at speed. Emission follows velocity, so a slow hand leaves almost nothing and
  a fast swipe draws a bright arc.
- **Glass answers.** Touching a card sends a wave out from the exact point of
  contact, aspect-corrected so it is round rather than oval, fading with both
  age and distance.
- **The world responds to speech.** Mote attraction, the awake rim and the
  presence orb all read the live speech envelope.

## Two-handed gestures

`src/gesture/detectors/twoHand.ts` is the one detector that cannot live in a
hand slot, because its entire subject is the relationship between two hands.

| Gesture | Result |
|---|---|
| Both hands pinched, moved apart or together | **Zoom** — a continuous dial on the ring radius |
| Pinched and drawn together past the threshold | **Group** — gathers and selects the focused module |
| Pinched and drawn apart past the threshold | **Split** — fans the ring out and clears the selection |
| Both palms open, held wide | **Multi-select** — marks the three modules facing you |
| Pinch and release with speed | **Throw** — the card leaves under Rapier physics |

The dial is a physical control with no threshold and no cooldown: you simply
stop when it looks right. The discrete gestures at either end **latch** once
committed, so a wobble at the boundary cannot fire "group" and "split"
alternately.
