/**
 * NEXUS audio.
 *
 * Every sound in this system is synthesised at runtime - there is not a single
 * audio asset in the bundle. That is a deliberate constraint: an OS should
 * boot instantly, and a 2 MB pack of UI blips is dead weight when the same
 * material can be built from three oscillators and a noise buffer.
 *
 * Signal flow:
 *
 *   pad / drone / noise bed ─┐
 *                            ├─> ambientBus ─> masterFilter ─┐
 *   ui voices ──> dryBus ─────┘                              ├─> limiter ─> out
 *              └> reverbSend ─> convolver ─> reverbReturn ───┘
 */

type Env = { attack: number; decay: number; peak: number };

const clampGain = (v: number) => (v < 0.0001 ? 0.0001 : v > 1 ? 1 : v);

export class AudioEngine {
  private ctx: AudioContext | null = null;
  private master!: GainNode;
  private limiter!: DynamicsCompressorNode;
  private ambientBus!: GainNode;
  private dryBus!: GainNode;
  private reverbSend!: GainNode;
  private reverbReturn!: GainNode;
  private convolver!: ConvolverNode;
  private noiseBuffer!: AudioBuffer;
  private padVoices: OscillatorNode[] = [];
  private lfo: OscillatorNode | null = null;
  private started = false;
  private muted = false;
  /** Rate limiter so a fast gesture stream cannot machine-gun the mix. */
  private lastVoiceAt = 0;
  private voiceCount = 0;

  get ready(): boolean {
    return this.started && this.ctx?.state === 'running';
  }

  get state(): string {
    return this.ctx?.state ?? 'closed';
  }

  /** Must be called from a user gesture. Safe to call repeatedly. */
  async unlock(): Promise<boolean> {
    if (typeof window === 'undefined') return false;
    if (!this.ctx) {
      const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return false;
      this.ctx = new Ctor({ latencyHint: 'interactive' });
      this.build();
    }
    if (this.ctx.state === 'suspended') await this.ctx.resume();
    if (!this.started) {
      this.startAmbient();
      this.started = true;
    }
    return this.ctx.state === 'running';
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.master.gain.cancelScheduledValues(t);
    this.master.gain.setTargetAtTime(muted ? 0.0001 : 0.55, t, 0.25);
  }

  dispose(): void {
    if (!this.ctx) return;
    this.padVoices.forEach((o) => {
      try {
        o.stop();
      } catch {
        /* already stopped */
      }
    });
    this.padVoices = [];
    this.lfo?.stop();
    this.lfo = null;
    void this.ctx.close();
    this.ctx = null;
    this.started = false;
  }

  private build(): void {
    const ctx = this.ctx!;

    this.limiter = ctx.createDynamicsCompressor();
    this.limiter.threshold.value = -12;
    this.limiter.knee.value = 6;
    this.limiter.ratio.value = 12;
    this.limiter.attack.value = 0.003;
    this.limiter.release.value = 0.25;
    this.limiter.connect(ctx.destination);

    this.master = ctx.createGain();
    this.master.gain.value = 0.0001;
    this.master.connect(this.limiter);
    // Fade in rather than punching a hole in the room.
    this.master.gain.setTargetAtTime(0.55, ctx.currentTime, 1.4);

    this.convolver = ctx.createConvolver();
    this.convolver.buffer = this.makeImpulse(3.4, 2.6);

    this.reverbReturn = ctx.createGain();
    this.reverbReturn.gain.value = 0.75;
    this.convolver.connect(this.reverbReturn);
    this.reverbReturn.connect(this.master);

    this.reverbSend = ctx.createGain();
    this.reverbSend.gain.value = 0.5;
    this.reverbSend.connect(this.convolver);

    this.dryBus = ctx.createGain();
    this.dryBus.gain.value = 0.9;
    this.dryBus.connect(this.master);

    this.ambientBus = ctx.createGain();
    this.ambientBus.gain.value = 0.34;
    this.ambientBus.connect(this.master);
    this.ambientBus.connect(this.reverbSend);

    this.noiseBuffer = this.makeNoise(2);
  }

  /** Exponentially decaying noise burst - a convincing hall without a file. */
  private makeImpulse(seconds: number, decay: number): AudioBuffer {
    const ctx = this.ctx!;
    const rate = ctx.sampleRate;
    const length = Math.floor(rate * seconds);
    const buffer = ctx.createBuffer(2, length, rate);
    for (let ch = 0; ch < 2; ch++) {
      const data = buffer.getChannelData(ch);
      for (let i = 0; i < length; i++) {
        const t = i / length;
        // Slight pre-delay keeps transients readable before the tail blooms.
        const gate = t < 0.012 ? t / 0.012 : 1;
        data[i] = (Math.random() * 2 - 1) * Math.pow(1 - t, decay) * gate;
      }
    }
    return buffer;
  }

  /** Pink-ish noise via a cheap one-pole cascade. Warmer than white. */
  private makeNoise(seconds: number): AudioBuffer {
    const ctx = this.ctx!;
    const length = Math.floor(ctx.sampleRate * seconds);
    const buffer = ctx.createBuffer(1, length, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    let b0 = 0;
    let b1 = 0;
    let b2 = 0;
    for (let i = 0; i < length; i++) {
      const white = Math.random() * 2 - 1;
      b0 = 0.99765 * b0 + white * 0.099;
      b1 = 0.963 * b1 + white * 0.2965;
      b2 = 0.57 * b2 + white * 1.0526;
      data[i] = (b0 + b1 + b2 + white * 0.1848) * 0.16;
    }
    return buffer;
  }

  /**
   * The bed: a slow, wide minor-ninth pad plus a sub drone and an air layer.
   * Detuning is deliberately uneven so the beating never locks into a pattern.
   */
  private startAmbient(): void {
    const ctx = this.ctx!;
    const now = ctx.currentTime;

    // A2 / E3 / B3 / F#4 - open fifths stacked, no third, so it stays neutral.
    const partials: Array<[number, number, OscillatorType]> = [
      [55, 0.5, 'sine'],
      [110.0, 0.26, 'triangle'],
      [164.81, 0.2, 'sawtooth'],
      [246.94, 0.12, 'sawtooth'],
      [369.99, 0.07, 'triangle'],
    ];

    const padFilter = ctx.createBiquadFilter();
    padFilter.type = 'lowpass';
    padFilter.frequency.value = 520;
    padFilter.Q.value = 0.8;
    padFilter.connect(this.ambientBus);

    // Filter breathing - the reason the room feels alive rather than looped.
    this.lfo = ctx.createOscillator();
    this.lfo.frequency.value = 0.037;
    const lfoDepth = ctx.createGain();
    lfoDepth.gain.value = 280;
    this.lfo.connect(lfoDepth);
    lfoDepth.connect(padFilter.frequency);
    this.lfo.start(now);

    for (const [freq, gain, type] of partials) {
      const osc = ctx.createOscillator();
      osc.type = type;
      osc.frequency.value = freq;
      osc.detune.value = (Math.random() - 0.5) * 11;

      const vca = ctx.createGain();
      vca.gain.value = 0.0001;
      vca.gain.setTargetAtTime(gain * 0.25, now, 3.2);

      // Independent slow tremolo per partial.
      const trem = ctx.createOscillator();
      trem.frequency.value = 0.04 + Math.random() * 0.06;
      const tremDepth = ctx.createGain();
      tremDepth.gain.value = gain * 0.08;
      trem.connect(tremDepth);
      tremDepth.connect(vca.gain);
      trem.start(now);

      osc.connect(vca);
      vca.connect(padFilter);
      osc.start(now);
      this.padVoices.push(osc, trem);
    }

    // Air layer: filtered noise, barely audible, gives the fog a texture.
    const air = ctx.createBufferSource();
    air.buffer = this.noiseBuffer;
    air.loop = true;
    const airFilter = ctx.createBiquadFilter();
    airFilter.type = 'bandpass';
    airFilter.frequency.value = 2600;
    airFilter.Q.value = 0.5;
    const airGain = ctx.createGain();
    airGain.gain.value = 0.0001;
    airGain.gain.setTargetAtTime(0.05, now, 4);
    air.connect(airFilter);
    airFilter.connect(airGain);
    airGain.connect(this.ambientBus);
    air.start(now);
  }

  /** Shared voice allocator with a hard ceiling and a minimum spacing. */
  private allocate(now: number): boolean {
    if (this.muted || !this.ctx || this.ctx.state !== 'running') return false;
    if (now - this.lastVoiceAt < 0.012) return false;
    if (this.voiceCount > 14) return false;
    this.lastVoiceAt = now;
    this.voiceCount++;
    window.setTimeout(() => {
      this.voiceCount = Math.max(0, this.voiceCount - 1);
    }, 900);
    return true;
  }

  private tone(
    freq: number,
    type: OscillatorType,
    env: Env,
    opts: { send?: number; pan?: number; sweepTo?: number; q?: number } = {},
  ): void {
    const ctx = this.ctx!;
    const t = ctx.currentTime;

    const osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    if (opts.sweepTo) osc.frequency.exponentialRampToValueAtTime(opts.sweepTo, t + env.decay);

    const vca = ctx.createGain();
    vca.gain.setValueAtTime(0.0001, t);
    vca.gain.exponentialRampToValueAtTime(clampGain(env.peak), t + env.attack);
    vca.gain.exponentialRampToValueAtTime(0.0001, t + env.attack + env.decay);

    const panner = ctx.createStereoPanner();
    panner.pan.value = opts.pan ?? 0;

    osc.connect(vca);
    vca.connect(panner);
    panner.connect(this.dryBus);
    if (opts.send) {
      const send = ctx.createGain();
      send.gain.value = opts.send;
      panner.connect(send);
      send.connect(this.reverbSend);
    }

    osc.start(t);
    osc.stop(t + env.attack + env.decay + 0.05);
  }

  private noiseBurst(
    freq: number,
    q: number,
    env: Env,
    opts: { send?: number; pan?: number; sweepTo?: number } = {},
  ): void {
    const ctx = this.ctx!;
    const t = ctx.currentTime;

    const src = ctx.createBufferSource();
    src.buffer = this.noiseBuffer;
    src.loop = true;

    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.setValueAtTime(freq, t);
    filter.Q.value = q;
    if (opts.sweepTo) filter.frequency.exponentialRampToValueAtTime(opts.sweepTo, t + env.decay);

    const vca = ctx.createGain();
    vca.gain.setValueAtTime(0.0001, t);
    vca.gain.exponentialRampToValueAtTime(clampGain(env.peak), t + env.attack);
    vca.gain.exponentialRampToValueAtTime(0.0001, t + env.attack + env.decay);

    const panner = ctx.createStereoPanner();
    panner.pan.value = opts.pan ?? 0;

    src.connect(filter);
    filter.connect(vca);
    vca.connect(panner);
    panner.connect(this.dryBus);
    if (opts.send) {
      const send = ctx.createGain();
      send.gain.value = opts.send;
      panner.connect(send);
      send.connect(this.reverbSend);
    }

    src.start(t);
    src.stop(t + env.attack + env.decay + 0.05);
  }

  // ---------------------------------------------------------------------
  // The UI voice set. Kept tight and tonal so it never fights the pad:
  // everything is drawn from the same A-minor-ish set the drone implies.
  // ---------------------------------------------------------------------

  /** Card came under the cursor / reticle. Almost subliminal. */
  hover(pan = 0): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(1318.5, 'sine', { attack: 0.004, decay: 0.07, peak: 0.05 }, { pan, send: 0.15 });
  }

  /** Discrete UI tick - slot changes, log entries. */
  tick(pan = 0): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(2093, 'sine', { attack: 0.002, decay: 0.045, peak: 0.045 }, { pan, send: 0.1 });
  }

  /** Pinch closed on a card. A short, dry, physical click plus a low body. */
  grab(pan = 0): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.noiseBurst(1800, 4, { attack: 0.002, decay: 0.055, peak: 0.11 }, { pan });
    this.tone(174.6, 'triangle', { attack: 0.003, decay: 0.13, peak: 0.13 }, { pan, send: 0.2 });
  }

  /** Pinch released. Falling interval - the card is leaving your hand. */
  release(power = 0.5, pan = 0): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    const p = clampGain(0.08 + power * 0.1);
    this.tone(659.3, 'triangle', { attack: 0.004, decay: 0.22, peak: p }, { pan, send: 0.4, sweepTo: 329.6 });
    this.noiseBurst(900, 1.2, { attack: 0.01, decay: 0.3, peak: 0.05 }, { pan, send: 0.5, sweepTo: 300 });
  }

  /** Carousel rotation. Panned into the direction of travel. */
  whoosh(direction: -1 | 1, intensity = 1): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    const pan = direction * 0.55;
    this.noiseBurst(
      520,
      0.9,
      { attack: 0.02, decay: 0.34, peak: clampGain(0.07 * intensity) },
      { pan, send: 0.6, sweepTo: direction > 0 ? 2400 : 240 },
    );
    this.tone(220, 'sine', { attack: 0.01, decay: 0.2, peak: 0.05 }, { pan: -pan, send: 0.3 });
  }

  /** Selection lock. Rising perfect fifth, the system's "yes". */
  confirm(pan = 0): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(659.3, 'sine', { attack: 0.004, decay: 0.09, peak: 0.09 }, { pan, send: 0.3 });
    window.setTimeout(() => {
      if (this.ctx?.state === 'running') {
        this.tone(987.8, 'sine', { attack: 0.004, decay: 0.16, peak: 0.08 }, { pan, send: 0.45 });
      }
    }, 62);
  }

  /** Card expands toward the viewer. Wide, blooming, reverb-heavy. */
  expand(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(329.6, 'triangle', { attack: 0.02, decay: 0.5, peak: 0.09 }, { send: 0.7, sweepTo: 494 });
    this.tone(987.8, 'sine', { attack: 0.05, decay: 0.6, peak: 0.045 }, { send: 0.8 });
  }

  /** Card collapses back into the ring. Inverse of expand. */
  collapse(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(494, 'triangle', { attack: 0.01, decay: 0.34, peak: 0.07 }, { send: 0.5, sweepTo: 246.9 });
  }

  /** Palm-hold freeze engaged. Deep, still, slightly dissonant. */
  freeze(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(110, 'sine', { attack: 0.05, decay: 0.9, peak: 0.13 }, { send: 0.6 });
    this.tone(1567.98, 'sine', { attack: 0.12, decay: 1.1, peak: 0.03 }, { send: 0.9 });
  }

  /** Freeze released. */
  thaw(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(146.8, 'sine', { attack: 0.02, decay: 0.5, peak: 0.09 }, { send: 0.5, sweepTo: 220 });
  }

  /** Reserved AI gesture recognised. Shimmering, unresolved on purpose. */
  arcane(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    [523.25, 783.99, 1174.66].forEach((f, i) => {
      window.setTimeout(() => {
        if (this.ctx?.state === 'running') {
          this.tone(f, 'sine', { attack: 0.01, decay: 0.42, peak: 0.05 }, { send: 0.85 });
        }
      }, i * 55);
    });
  }

  /** Action refused - the only place the warning colour has an audio twin. */
  deny(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(155.6, 'square', { attack: 0.002, decay: 0.1, peak: 0.06 }, { send: 0.15 });
  }

  /** Boot chime. Plays once, under the title card. */
  boot(): void {
    if (!this.ctx || this.ctx.state !== 'running') return;
    [220, 329.6, 493.9, 659.3].forEach((f, i) => {
      window.setTimeout(() => {
        if (this.ctx?.state === 'running') {
          this.tone(f, 'sine', { attack: 0.03, decay: 0.7 + i * 0.12, peak: 0.06 }, { send: 0.8 });
        }
      }, i * 150);
    });
  }

  // ---------------------------------------------------------------------
  // Phase 2: the assistant's voice.
  //
  // Speech is routed through a PannerNode so it has a POSITION in the room
  // rather than arriving flat in both ears. That is the whole reason the TTS
  // route returns raw PCM: the browser's own SpeechSynthesis writes straight
  // to the output device and cannot be routed through Web Audio at all, so it
  // can never be spatialised.
  // ---------------------------------------------------------------------

  private voiceInput: GainNode | null = null;
  private voicePanner: PannerNode | null = null;
  private voiceAnalyser: AnalyserNode | null = null;
  private levelBuffer: Uint8Array | null = null;

  /**
   * Lazily build the voice chain. Returns null before `unlock()`, which is the
   * correct answer rather than an error - there is no audio graph yet.
   */
  voiceChannel(): { ctx: AudioContext; input: GainNode; analyser: AnalyserNode } | null {
    if (!this.ctx || !this.started) return null;
    if (this.voiceInput && this.voiceAnalyser) {
      return { ctx: this.ctx, input: this.voiceInput, analyser: this.voiceAnalyser };
    }

    const ctx = this.ctx;

    const input = ctx.createGain();
    input.gain.value = 1;

    // Speech sits above the pad without being shouty; a gentle high-pass keeps
    // it out of the drone's register.
    const shelf = ctx.createBiquadFilter();
    shelf.type = 'highpass';
    shelf.frequency.value = 110;

    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.72;

    const panner = ctx.createPanner();
    panner.panningModel = 'HRTF';
    panner.distanceModel = 'inverse';
    panner.refDistance = 1.6;
    panner.maxDistance = 40;
    panner.rolloffFactor = 0.7;
    // Directly ahead of the seated viewer, at the centre of the ring.
    panner.positionX?.setValueAtTime(0, ctx.currentTime);
    panner.positionY?.setValueAtTime(0.35, ctx.currentTime);
    panner.positionZ?.setValueAtTime(0, ctx.currentTime);

    input.connect(shelf);
    shelf.connect(analyser);
    analyser.connect(panner);
    panner.connect(this.master);

    // A touch of the same room reverb everything else uses, so the voice
    // belongs to the space rather than sitting on top of it.
    const send = ctx.createGain();
    send.gain.value = 0.22;
    panner.connect(send);
    send.connect(this.reverbSend);

    this.voiceInput = input;
    this.voicePanner = panner;
    this.voiceAnalyser = analyser;
    this.levelBuffer = new Uint8Array(analyser.frequencyBinCount);
    return { ctx, input, analyser };
  }

  /** Move the voice source. Used when the assistant presence drifts. */
  setVoicePosition(x: number, y: number, z: number): void {
    const panner = this.voicePanner;
    if (!panner || !this.ctx) return;
    const t = this.ctx.currentTime;
    if (panner.positionX) {
      panner.positionX.setTargetAtTime(x, t, 0.08);
      panner.positionY!.setTargetAtTime(y, t, 0.08);
      panner.positionZ!.setTargetAtTime(z, t, 0.08);
    } else {
      panner.setPosition(x, y, z);
    }
  }

  /**
   * Keep the Web Audio listener aligned with the drifting camera, otherwise
   * the voice appears to swing around the room as the camera floats.
   */
  setListener(
    px: number, py: number, pz: number,
    fx: number, fy: number, fz: number,
  ): void {
    if (!this.ctx) return;
    const l = this.ctx.listener;
    const t = this.ctx.currentTime;
    if (l.positionX) {
      l.positionX.setTargetAtTime(px, t, 0.05);
      l.positionY.setTargetAtTime(py, t, 0.05);
      l.positionZ.setTargetAtTime(pz, t, 0.05);
      l.forwardX.setTargetAtTime(fx, t, 0.05);
      l.forwardY.setTargetAtTime(fy, t, 0.05);
      l.forwardZ.setTargetAtTime(fz, t, 0.05);
      l.upX.setTargetAtTime(0, t, 0.05);
      l.upY.setTargetAtTime(1, t, 0.05);
      l.upZ.setTargetAtTime(0, t, 0.05);
    } else {
      l.setPosition(px, py, pz);
      l.setOrientation(fx, fy, fz, 0, 1, 0);
    }
  }

  /** Current speech loudness, 0..1. Drives the presence orb and the glow. */
  voiceLevel(): number {
    const analyser = this.voiceAnalyser;
    const buffer = this.levelBuffer;
    if (!analyser || !buffer) return 0;
    analyser.getByteTimeDomainData(buffer as Uint8Array<ArrayBuffer>);
    let peak = 0;
    for (let i = 0; i < buffer.length; i += 2) {
      const v = Math.abs(buffer[i]! - 128) / 128;
      if (v > peak) peak = v;
    }
    return peak > 1 ? 1 : peak;
  }

  /** Pull the ambient bed down while the assistant talks, then let it back. */
  duck(amount: number): void {
    if (!this.ctx) return;
    const target = clampGain(0.34 * (1 - amount * 0.62));
    this.ambientBus.gain.setTargetAtTime(target, this.ctx.currentTime, 0.18);
  }

  /** Soft rising chime when the assistant wakes. */
  wake(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    [329.6, 493.9, 659.3].forEach((f, i) => {
      window.setTimeout(() => {
        if (this.ctx?.state === 'running') {
          this.tone(f, 'sine', { attack: 0.012, decay: 0.5, peak: 0.06 }, { send: 0.7 });
        }
      }, i * 48);
    });
  }

  /** Falling counterpart, on returning to standby. */
  sleep(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.tone(392, 'sine', { attack: 0.02, decay: 0.55, peak: 0.055 }, { send: 0.6, sweepTo: 196 });
  }

  /** Short dry tick when the user cuts the assistant off. */
  cut(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.noiseBurst(2400, 6, { attack: 0.001, decay: 0.05, peak: 0.07 }, {});
  }

  // ---------------------------------------------------------------------
  // Phase 3: spectral analysis for the Music module.
  //
  // There is no track playing, and pretending otherwise would be the exact
  // placeholder this phase exists to remove. What the module shows instead is
  // real: a live spectrum of everything this environment is actually
  // generating - the ambient pad, the drone, the air layer, every UI voice and
  // the assistant speaking. It is a spectrum analyser pointed at the room.
  // ---------------------------------------------------------------------

  private masterAnalyser: AnalyserNode | null = null;
  private spectrumBins: Uint8Array | null = null;

  /** Insert an analyser between the master bus and the limiter, once. */
  private ensureAnalyser(): AnalyserNode | null {
    if (this.masterAnalyser) return this.masterAnalyser;
    if (!this.ctx || !this.started) return null;

    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.78;

    // master -> analyser -> limiter, replacing master -> limiter.
    this.master.disconnect();
    this.master.connect(analyser);
    analyser.connect(this.limiter);

    this.masterAnalyser = analyser;
    this.spectrumBins = new Uint8Array(analyser.frequencyBinCount);
    return analyser;
  }

  /**
   * Fill `out` with a logarithmically-spaced spectrum in 0..1.
   *
   * Log spacing because linear FFT bins put almost everything musical in the
   * leftmost eighth of the display; the ear is logarithmic and the readout
   * should be too.
   */
  spectrum(out: Float32Array): boolean {
    const analyser = this.ensureAnalyser();
    const bins = this.spectrumBins;
    if (!analyser || !bins) return false;

    analyser.getByteFrequencyData(bins as Uint8Array<ArrayBuffer>);

    const bands = out.length;
    const nyquist = (this.ctx?.sampleRate ?? 48000) / 2;
    const minHz = 40;
    const maxHz = Math.min(16000, nyquist);
    const ratio = Math.log(maxHz / minHz);

    for (let i = 0; i < bands; i++) {
      const lo = minHz * Math.exp((i / bands) * ratio);
      const hi = minHz * Math.exp(((i + 1) / bands) * ratio);
      const loBin = Math.max(0, Math.floor((lo / nyquist) * bins.length));
      const hiBin = Math.min(bins.length - 1, Math.ceil((hi / nyquist) * bins.length));

      let peak = 0;
      for (let b = loBin; b <= hiBin; b++) if (bins[b]! > peak) peak = bins[b]!;
      out[i] = peak / 255;
    }
    return true;
  }

  /** Overall output level, 0..1. */
  masterLevel(): number {
    const analyser = this.ensureAnalyser();
    const bins = this.spectrumBins;
    if (!analyser || !bins) return 0;
    analyser.getByteFrequencyData(bins as Uint8Array<ArrayBuffer>);
    let sum = 0;
    for (let i = 0; i < bins.length; i++) sum += bins[i]!;
    return Math.min(1, sum / bins.length / 160);
  }

  /**
   * World morph. A slow filtered sweep rather than a hit: the room is
   * changing around you, and a percussive cue would make it feel like a
   * button press instead of a place.
   */
  morph(): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.noiseBurst(280, 0.7, { attack: 0.35, decay: 1.5, peak: 0.09 }, { send: 0.85, sweepTo: 3200 });
    this.tone(98, 'sine', { attack: 0.4, decay: 1.6, peak: 0.075 }, { send: 0.7, sweepTo: 196 });
  }

  /** Very small tick used by micro-interactions. Quieter than `tick`. */
  brush(pan = 0): void {
    if (!this.allocate(this.ctx?.currentTime ?? 0)) return;
    this.noiseBurst(5200, 8, { attack: 0.001, decay: 0.035, peak: 0.028 }, { pan });
  }
}

/** Process-wide singleton - one AudioContext per document, always. */
let instance: AudioEngine | null = null;

export function getAudio(): AudioEngine {
  instance ??= new AudioEngine();
  return instance;
}
