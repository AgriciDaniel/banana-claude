#!/usr/bin/env node
/**
 * Generate the machine's face, once.
 *
 * A face is the one thing the body's geometry cannot reach. The trunk and the
 * limbs are lathes -- profiles revolved around an axis -- and a lathe is
 * rotationally symmetric by construction, so it can produce a skull but never a
 * brow, a nose or a mouth. Sculpting those from primitives at the size this
 * figure stands would be a handful of unreadable lumps.
 *
 * This project already knows how to make an image, so the face is made by the
 * same model the assistant uses for everything else, and cached to disk. Run
 * once; regenerate with `npm run make:face -- --force`.
 *
 * Unlike the first version of this, the face is now lit rather than added: it
 * sits on an opaque shell and takes the same key light as the rest of the body.
 * So the prompt asks for a face lit flatly and from the front, with no baked
 * shadow of its own to fight the room's.
 *
 * Stdlib only, like every other script here.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const OUT_DIR = resolve(root, 'public/avatar');
/* Named by what the model actually returns. It answers with JPEG by default,
 * and writing those bytes to a .png worked only because browsers sniff -- the
 * name was simply a lie, and it made the file unreadable to anything stricter. */
const NAMES = { 'image/png': 'face.png', 'image/jpeg': 'face.jpg', 'image/webp': 'face.webp' };

const MODEL = process.env.GEMINI_IMAGE_MODEL ?? 'gemini-3.1-flash-image';
const API = 'https://generativelanguage.googleapis.com/v1beta/models';

/*
 * Framing matters more than styling. The image is mapped onto a plane the width
 * of the skull, so the face must fill the frame square-on and symmetrically --
 * a three-quarter view or a head-and-shoulders crop lands the features
 * somewhere the geometry is not.
 *
 * Mouth closed and neutral, because the figure opens it itself: the rows around
 * the lips are stretched in the shader on the speech envelope, so a mouth that
 * arrives already open has nowhere to go.
 */
const PROMPT = [
  'The face of a white ceramic humanoid robot, seen exactly front-on, perfectly symmetrical.',
  'Sculpted like a human face: brow ridge, cheekbones, a real nose, closed neutral lips, a defined jaw.',
  'Fine panel seams trace the forehead, the cheeks and the jawline, with thin cyan light in the seams.',
  'The eyes are glowing amber optics set in human-shaped eye sockets, looking straight at the camera.',
  'A narrow violet light bar across the brow.',
  'Glossy white ceramic shell, photorealistic, sharp detail, lit flatly and evenly from the front.',
  'The face fills the frame edge to edge: forehead at the top, chin at the bottom.',
  'Pure black background, no hair, no neck, no shoulders, no text, no watermark, no border.',
].join(' ');

function readKey() {
  if (process.env.GEMINI_API_KEY) return process.env.GEMINI_API_KEY;
  const envFile = resolve(root, '.env.local');
  if (!existsSync(envFile)) return null;
  const match = readFileSync(envFile, 'utf8').match(/^GEMINI_API_KEY=(.+)$/m);
  return match ? match[1].trim() : null;
}

async function main() {
  const force = process.argv.includes('--force');
  const already = Object.values(NAMES)
    .map((file) => resolve(OUT_DIR, file))
    .find((path) => existsSync(path));
  if (already && !force) {
    console.log(`face already generated: ${already}`);
    console.log('(pass --force to make a new one)');
    return;
  }

  const key = readKey();
  if (!key) {
    console.error('GEMINI_API_KEY is not set, and no .env.local carries one.');
    console.error('The figure falls back to a plain visor without it -- this is optional.');
    process.exitCode = 1;
    return;
  }

  console.log(`asking ${MODEL} for a face...`);
  const response = await fetch(`${API}/${MODEL}:generateContent`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
    body: JSON.stringify({
      contents: [{ role: 'user', parts: [{ text: PROMPT }] }],
      generationConfig: {
        responseModalities: ['IMAGE'],
        // Square, so the crop the figure applies is the whole frame.
        imageConfig: { imageSize: '1K', aspectRatio: '1:1' },
      },
    }),
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    console.error(`image model returned ${response.status}: ${detail.slice(0, 300)}`);
    process.exitCode = 1;
    return;
  }

  const payload = await response.json();
  const candidate = payload.candidates?.[0];
  const inline = candidate?.content?.parts?.find((p) => p.inlineData)?.inlineData;
  if (!inline?.data) {
    console.error(`no image came back (${candidate?.finishReason ?? 'no reason given'})`);
    process.exitCode = 1;
    return;
  }

  const mime = inline.mimeType ?? 'image/png';
  const name = NAMES[mime];
  if (!name) {
    console.error(`the model returned ${mime}, which is not an image type the figure loads.`);
    process.exitCode = 1;
    return;
  }

  mkdirSync(OUT_DIR, { recursive: true });
  const out = resolve(OUT_DIR, name);
  writeFileSync(out, Buffer.from(inline.data, 'base64'));
  console.log(`wrote ${out}`);
  /* The figure crops whatever comes back to its centre square, so a landscape
   * frame loses its sides rather than stretching the face. Nothing to check
   * here: it reads the real dimensions off the loaded texture. */
}

main().catch((error) => {
  console.error(String(error));
  process.exitCode = 1;
});
