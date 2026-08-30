# Post-Processing Pipeline Reference

> Load this on-demand when the user needs image manipulation after generation.

## Prerequisites

External-tool examples below assume the user has selected an asset directory
and the shell is in that exact directory:

```bash
cd "/absolute/path/to/the/asset-directory"
```

If changing directory is undesirable, replace every relative input and output
with an absolute path. Bundled Banana scripts are invoked through
`$CLAUDE_SKILL_DIR` and do not depend on the current directory.

Check availability before using:
```bash
which magick    # ImageMagick 7 (preferred)
which convert   # ImageMagick 6 (fallback)
which ffmpeg    # For video/animation
```

Do not install system packages without the user's approval. If ImageMagick is
absent, report the missing optional dependency and provide the relevant package
manager command instead of running it automatically.

Load this fail-closed renderer before any output-producing example. The external
tool receives only a path inside a unique mode-0700 directory beside the final
destination. After the tool exits successfully, the helper accepts exactly one
nonempty, regular, single-link file and publishes it with `os.link()`. That link
operation is atomic and no-replace: if the requested destination appears at any
time before publication, publication fails without changing it. After the
temporary link is removed, the requested destination is one single-link final
file.

```bash
banana_render_new_destination() {
  python3 - "$@" <<'PY'
import os
import shutil
import stat
import subprocess
import sys
import tempfile

TOKEN = "__BANANA_RENDER_OUTPUT__"


def reject(message):
    raise RuntimeError(message)


if len(sys.argv) < 4:
    print("usage: DESTINATION COMMAND... __BANANA_RENDER_OUTPUT__", file=sys.stderr)
    raise SystemExit(2)

destination = os.path.abspath(sys.argv[1])
command = sys.argv[2:]
parent, basename = os.path.split(destination)
if not basename or command.count(TOKEN) != 1:
    print("Refusing an unsafe destination or output placeholder", file=sys.stderr)
    raise SystemExit(2)
if not os.path.isdir(parent) or os.path.islink(parent):
    print("Refusing a missing or symlinked destination directory", file=sys.stderr)
    raise SystemExit(2)
parent_info = os.lstat(parent)
if parent_info.st_mode & 0o022 or (
    hasattr(os, "geteuid") and parent_info.st_uid != os.geteuid()
):
    print("Refusing a destination directory not controlled by this user", file=sys.stderr)
    raise SystemExit(2)
if os.path.lexists(destination):
    print("Refusing an existing destination", file=sys.stderr)
    raise SystemExit(1)

temporary_directory = None
published_identity = None
status = 1
try:
    temporary_directory = tempfile.mkdtemp(
        prefix=f".{basename}.banana-render-", dir=parent
    )
    temporary_info = os.lstat(temporary_directory)
    if not stat.S_ISDIR(temporary_info.st_mode) or temporary_info.st_mode & 0o077:
        reject("temporary directory is not private")
    rendered = os.path.join(temporary_directory, basename)
    completed = subprocess.run(
        [rendered if item == TOKEN else item for item in command], check=False
    )
    if completed.returncode != 0:
        reject(f"renderer exited with status {completed.returncode}")
    if os.listdir(temporary_directory) != [basename]:
        reject("renderer produced an unexpected temporary file set")
    rendered_info = os.lstat(rendered)
    if (
        not stat.S_ISREG(rendered_info.st_mode)
        or rendered_info.st_nlink != 1
        or rendered_info.st_size == 0
    ):
        reject("renderer did not produce one nonempty single-link regular file")
    identity = (rendered_info.st_dev, rendered_info.st_ino)
    published_identity = identity
    try:
        os.link(rendered, destination, follow_symlinks=False)
    except FileExistsError:
        published_identity = None
        reject("destination appeared before atomic no-replace publication")
    linked_info = os.lstat(destination)
    rendered_info = os.lstat(rendered)
    if (
        (linked_info.st_dev, linked_info.st_ino) != identity
        or (rendered_info.st_dev, rendered_info.st_ino) != identity
        or linked_info.st_nlink != 2
        or rendered_info.st_nlink != 2
    ):
        reject("published link identity could not be verified")
    os.unlink(rendered)
    final_info = os.lstat(destination)
    if (
        (final_info.st_dev, final_info.st_ino) != identity
        or not stat.S_ISREG(final_info.st_mode)
        or final_info.st_nlink != 1
    ):
        reject("final destination is not the verified single-link file")
    os.rmdir(temporary_directory)
    temporary_directory = None
    published_identity = None
    status = 0
except (OSError, RuntimeError, TypeError) as error:
    print(f"Refusing derived output: {error}", file=sys.stderr)
finally:
    if published_identity is not None:
        try:
            current = os.lstat(destination)
            if (current.st_dev, current.st_ino) == published_identity:
                os.unlink(destination)
        except FileNotFoundError:
            pass
    if temporary_directory is not None:
        try:
            shutil.rmtree(temporary_directory)
        except OSError as cleanup_error:
            print(f"Temporary cleanup failed: {cleanup_error}", file=sys.stderr)
            status = 1

raise SystemExit(status)
PY
}
```

The helper call is mandatory for every fixed output and every computed
destination inside a loop. Pass the requested path only as the helper's first
argument, and pass exactly one quoted `"__BANANA_RENDER_OUTPUT__"` argument to
the renderer. Never give the requested destination to ImageMagick, FFmpeg, or
another renderer directly. Use a distinct destination for each alternative.
The helper's validation is a filesystem-integrity check, not image decoding,
pixel review, or confirmation that the transformation is visually correct.

This pattern requires Python, hard-link support, and local filesystem semantics.
It fails closed when hard links are unavailable. It also requires the immediate
destination directory to be owned by the current user and not group-writable or
world-writable. Publication and cleanup remain path-based, so no ancestor may be
renameable by an untrusted party. Process termination that cannot run `finally`,
such as `SIGKILL`, a power loss, or a host crash, can leave a hidden temporary
directory. If termination lands between `os.link()` and temporary-link removal,
both names can remain with link count two. A single-link final file is guaranteed
only after a successful helper return. Such termination cannot turn `os.link()`
into an overwrite of an existing destination. Treat the interrupted operation as
unreconciled. Inspect inode identity and link counts before removing only the
hidden `.DESTINATION.banana-render-*` workspace from the intended asset
directory.

## Provenance warning

Google documents SynthID on generated Gemini images. Some Google Cloud surfaces
also provide C2PA credentials. Cropping, recompression, format conversion,
metadata stripping, compositing, and other edits may remove metadata or make a
C2PA validator report that the asset changed. Preserve the original provider
output and its Banana metadata sidecar. Deliver a derived file separately and
record the transformations applied.

## Common Operations

### Exact-Copy Composition

Use the bundled zero-dependency SVG compositor when exact characters, a legal
line, or an approved brand font must not be regenerated:

```bash
banana_render_new_destination "final-exact-copy.svg" \
  python3 "$CLAUDE_SKILL_DIR/scripts/typeset.py" \
    --image input.png --text "EXACT APPROVED COPY" \
    --x 120 --y 180 --font-size 64 --font-weight 700 \
    --font-file approved-font.woff2 \
    --output "__BANANA_RENDER_OUTPUT__"
```

The SVG embeds the raster and, when supplied, the font bytes. It is byte
deterministic for the same inputs. Font rendering can still vary when no font is
embedded, so render and inspect the final delivery format.

Local input reads are bounded before parsing or embedding: text files are
limited to 1 MiB, ordered layer JSON files to 5 MiB, individual embedded fonts
to 10 MiB, and total composite source assets to 50 MiB.

For several text blocks or an exact supplied logo, use an ordered layer file:

```json
[
  {"type":"text","text":"EXACT HEADLINE","x":120,"y":180,"font_size":64,"font_weight":"700","fill":"#FFFFFF"},
  {"type":"image","path":"approved-logo.png","x":120,"y":760,"width":240,"height":80,"fit":"contain"}
]
```

```bash
banana_render_new_destination "final-layered.svg" \
  python3 "$CLAUDE_SKILL_DIR/scripts/typeset.py" --image input.png \
    --layers-file layers.json --output "__BANANA_RENDER_OUTPUT__"
```

Image layers accept trusted raster assets. Export and review an approved SVG
logo as a PNG first. The compositor refuses arbitrary source SVG so it cannot
silently embed active or externally loaded content. Inspect copy, logo geometry,
crop, and spacing in the rendered delivery artifact.

Render the SVG to a PNG or JPEG at the exact delivery dimensions with a trusted
local viewer, then review the preview together with the SVG. Without that
preview, automated pixel review is `BLOCKED`; request user inspection and do
not infer a Pass from markup.

### Resize for a destination

Do not use memorized social-platform dimensions. Ask for the destination's
current delivery specification or verify it in that destination's primary
publishing documentation. Freeze the required pixel canvas, crop behavior,
safe areas, format, file-size limit, alpha behavior, and color requirements.

After replacing the two task-specific placeholders with integers, this template
performs a center crop:

```bash
banana_target_width=REQUIRED_PIXEL_WIDTH
banana_target_height=REQUIRED_PIXEL_HEIGHT
banana_render_new_destination "destination-center-crop.png" \
  magick input.png \
    -resize "${banana_target_width}x${banana_target_height}^" \
    -gravity center \
    -extent "${banana_target_width}x${banana_target_height}" \
    "__BANANA_RENDER_OUTPUT__"
```

Center cropping is not universally appropriate. Reposition the crop when the
focal subject, text, logo, or required safe area would be clipped, then inspect
the delivery-size artifact.

### Background Removal (Transparency)

```bash
# Remove solid white background
banana_render_new_destination "white-background-removed.png" \
  magick input.png -fuzz 10% -transparent white \
    "__BANANA_RENDER_OUTPUT__"

# Remove solid color background (specify color)
banana_render_new_destination "color-background-removed.png" \
  magick input.png -fuzz 15% -transparent "#F0F0F0" \
    "__BANANA_RENDER_OUTPUT__"

# Clean edges after transparency (anti-alias)
banana_render_new_destination "transparency-edges-cleaned.png" \
  magick input.png -fuzz 10% -transparent white -channel A \
    -blur 0x1 -level 50%,100% "__BANANA_RENDER_OUTPUT__"

# Auto-crop transparent padding
banana_render_new_destination "transparency-trimmed.png" \
  magick input.png -trim +repage "__BANANA_RENDER_OUTPUT__"
```

### Format Conversion

```bash
# PNG to WebP (web-optimized, smaller file)
banana_render_new_destination "converted.webp" \
  magick input.png -quality 85 "__BANANA_RENDER_OUTPUT__"

# PNG to JPEG (with white background for transparency)
banana_render_new_destination "flattened.jpg" \
  magick input.png -background white -flatten -quality 90 \
    "__BANANA_RENDER_OUTPUT__"

# PNG to AVIF (modern, smallest size)
banana_render_new_destination "converted.avif" \
  magick input.png -quality 80 "__BANANA_RENDER_OUTPUT__"

# Approximate SVG trace, never a substitute for an approved vector logo master
banana_render_new_destination "traced.svg" \
  potrace input.pbm -s -o "__BANANA_RENDER_OUTPUT__"
```

Tracing can alter curves, counters, spacing, and small marks. Treat it as an
approximate reconstruction and compare it with the brand owner's approved
master before use. Exact-logo work should use the supplied approved vector or
a reviewed trusted raster layer.

### Color Adjustments

```bash
# Increase contrast
banana_render_new_destination "contrast-adjusted.png" \
  magick input.png -contrast-stretch 2%x1% "__BANANA_RENDER_OUTPUT__"

# Warm color temperature
banana_render_new_destination "warm-adjusted.png" \
  magick input.png -modulate 100,110,105 "__BANANA_RENDER_OUTPUT__"

# Cool color temperature
banana_render_new_destination "cool-adjusted.png" \
  magick input.png -modulate 100,90,95 "__BANANA_RENDER_OUTPUT__"

# Desaturate (muted colors)
banana_render_new_destination "desaturated.png" \
  magick input.png -modulate 100,70,100 "__BANANA_RENDER_OUTPUT__"

# Convert to grayscale
banana_render_new_destination "grayscale.png" \
  magick input.png -colorspace Gray "__BANANA_RENDER_OUTPUT__"

# Sepia tone
banana_render_new_destination "sepia.png" \
  magick input.png -sepia-tone 80% "__BANANA_RENDER_OUTPUT__"
```

### Compositing

```bash
# Overlay watermark (bottom-right, 20% opacity)
banana_render_new_destination "watermarked.png" \
  magick base.png watermark.png -gravity southeast -geometry +20+20 \
    -compose dissolve -define compose:args=20 -composite \
    "__BANANA_RENDER_OUTPUT__"

# Side-by-side comparison
banana_render_new_destination "comparison-horizontal.png" \
  magick input1.png input2.png +append "__BANANA_RENDER_OUTPUT__"

# Vertical stack
banana_render_new_destination "comparison-vertical.png" \
  magick input1.png input2.png -append "__BANANA_RENDER_OUTPUT__"

# Add padding/border
banana_render_new_destination "bordered.png" \
  magick input.png -bordercolor white -border 40 \
    "__BANANA_RENDER_OUTPUT__"

# Add rounded corners
banana_render_new_destination "rounded.png" \
  magick input.png \( +clone -alpha extract -draw \
    "roundrectangle 0,0,%[fx:w-1],%[fx:h-1],20,20" \) \
    -alpha off -compose CopyOpacity -composite \
    "__BANANA_RENDER_OUTPUT__"
```

### Batch Processing

```bash
# Resize all PNGs in directory
for f in ~/Documents/banana-claude/*.png; do
  banana_derived_output="${f%.png}_thumb.png"
  banana_render_new_destination "$banana_derived_output" \
    magick "$f" -resize 800x800 "__BANANA_RENDER_OUTPUT__" || exit 1
done

# Convert all to WebP
for f in ~/Documents/banana-claude/*.png; do
  banana_derived_output="${f%.png}.webp"
  banana_render_new_destination "$banana_derived_output" \
    magick "$f" -quality 85 "__BANANA_RENDER_OUTPUT__" || exit 1
done
```

## Animation (GIF/Video from Multiple Frames)

```bash
# Create GIF from multiple images
banana_render_new_destination "animation.gif" \
  magick -delay 100 frame1.png frame2.png frame3.png \
    "__BANANA_RENDER_OUTPUT__"

# Create MP4 from image sequence
banana_render_new_destination "slideshow.mp4" \
  ffmpeg -framerate 1 -pattern_type glob -i '*.png' \
    -c:v libx264 -pix_fmt yuv420p "__BANANA_RENDER_OUTPUT__"
```

## Derived-artifact manifest

Keep the provider original and its Banana sidecar unchanged. For every
accepted transform, store a separate manifest beside the derived artifact:

```json
{
  "schema_version": "banana.derived-artifact.v1",
  "source_artifact_sha256": "FULL_SHA256",
  "source_sidecar_sha256": "FULL_SHA256_OR_NULL",
  "derived_artifact_sha256": "FULL_SHA256",
  "operation": "resize-and-center-crop",
  "tool": "ImageMagick",
  "tool_version": "VERIFIED_LOCAL_VERSION",
  "parameters": {
    "canvas": "1200x628",
    "gravity": "center"
  },
  "visual_review_status": "needs_review"
}
```

Hash actual bytes after the transform. Record only the arguments that affected
the result, never credentials or unrelated absolute paths. A manifest proves
which source and settings were used, not that the derived pixels passed review.

## Note on larger output tiers

Gemini output pixels vary by model, tier, and aspect ratio. Treat the requested
tier as a provider setting, not a promise of memorized dimensions. Check the
actual artifact dimensions and destination requirements. Use a larger tier only
when delivery justifies the additional nominal output cost.

## Green Screen Transparency Pipeline

When the delivery requires a verified alpha channel, do not assume the model
output is transparent. Use a reviewed extraction or matting workflow. A simple
chroma-key route is suitable only for clean, high-contrast subjects:

### 1. Generate with a solid chroma background

For a new asset only, add a chroma-background requirement to the frozen brief.
Do not append it to a preservation edit when it conflicts with the original
background or other locks:
```
on a solid bright green (#00FF00) chroma key background
with clean edge separation between the subject and background
```

### 2. Remove green screen (ImageMagick)

```bash
banana_render_new_destination "subject-keyed-imagemagick.png" \
  magick input.png -fuzz 20% -transparent "#00FF00" \
    "__BANANA_RENDER_OUTPUT__"
```

### 3. Clean edges + trim (ImageMagick)

```bash
banana_render_new_destination "subject-keyed-clean-imagemagick.png" \
  magick subject-keyed-imagemagick.png -channel A -blur 0x1 \
    -level 50%,100% -trim +repage "__BANANA_RENDER_OUTPUT__"
```

### 4. Alternative (FFmpeg, better for batch)

```bash
banana_render_new_destination "subject-keyed-ffmpeg.png" \
  ffmpeg -i input.png \
    -vf "colorkey=0x00FF00:0.3:0.1,despill=type=green" \
    -pix_fmt rgba "__BANANA_RENDER_OUTPUT__"
```

### Tips

- `-fuzz 20%` handles slight color variation, but inspect the result before
  increasing it because a broader tolerance can erase intended colors.
- High-contrast edges help extraction but may still produce color spill.
- FFmpeg can process repeated assets efficiently and includes a despill stage.
- Always verify edges after conversion. Hair and fur may need manual touchup.
- For important hair, fur, glass, smoke, or translucent material, prefer a
  dedicated segmentation or matting workflow over chroma-key heuristics.

## Quality Assessment

```bash
# Get image dimensions and info
magick identify -verbose input.png | head -20

# Check file size
ls -lh input.png

# Get exact pixel dimensions
magick identify -format "%wx%h" input.png
```
