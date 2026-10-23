# Back Office Helper icon

This project owns the source artwork, animation builder and exported states in this directory.
The original mark's provenance and checksum are in `inputs.json`. Its geometry stays fixed;
separate Sequence accents communicate idle, thinking, working and error states. The working
motion represents cases progressing. It is illustrative activity, not measured progress.

`assets/backoffice/neutral/` contains four 128×128 transparent APNG loops, matching first-frame
stills and a reference identity layer. `catalog.json` records their hashes and frame timing.
Use `rendering: color` and `image_rendering: auto` in this project's existing agent workflow.
The named application pose uses the working loop; runtime policy, tools and agent identity stay
owned by their existing declarations.

The current host rejects animated masks and has no automatic palette selector. The production
export uses neutral ink (`#808080`, with retained raster shading) on both light and dark surfaces.
The host selects the first frame for reduced motion and surfaces that do not animate. Animation
plays locally through the existing icon cache, with no frame polling or extra connections.

## Rebuild

Use Node 22+ and Python 3.11+ from this directory:

```sh
npm ci
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
npm run build
npm run verify
```

The build preserves the source checksum and verifies all states animate, the identity pixels
stay fixed, frames fit the canvas, stills match frame zero, and the platform's file limits hold.
Exported assets are versioned with this project. A Git push applies them through the existing
workflow; a local build alone does not publish them.
