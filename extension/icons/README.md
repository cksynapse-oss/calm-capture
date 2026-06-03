# Calm Capture — Extension Icons

Place the following PNG icon files in this directory before loading the extension in Chrome:

| File          | Size     | Usage                                  |
|---------------|----------|----------------------------------------|
| `icon-16.png` | 16×16 px | Favicon / tab strip                    |
| `icon-48.png` | 48×48 px | Extensions management page             |
| `icon-128.png`| 128×128 px | Chrome Web Store / install dialog    |

## Design guidelines

- Background: `#0a0a0f` (near-black)
- Primary accent: `#5B8DEF` (luminous blue)
- The icon should render a minimal "capture" motif — e.g., a rounded square with a subtle plus or crosshair symbol in the accent colour.

## Quick placeholder (macOS)

If you need a quick placeholder for local development you can generate solid-colour PNGs
with ImageMagick:

```bash
magick -size 16x16  xc:'#5B8DEF' icons/icon-16.png
magick -size 48x48  xc:'#5B8DEF' icons/icon-48.png
magick -size 128x128 xc:'#5B8DEF' icons/icon-128.png
```

Or with sips (ships with macOS, no extra install):

```bash
python3 - <<'EOF'
from PIL import Image
for sz in [16, 48, 128]:
    img = Image.new("RGBA", (sz, sz), (91, 141, 239, 255))
    img.save(f"icons/icon-{sz}.png")
EOF
```
