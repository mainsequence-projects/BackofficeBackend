# Casekeeper

Casekeeper is the Back Office helper's approved teal folder character. These
five transparent PNGs are owned by this repository and declared by
`backoffice_helper` in `.mainsequence/workflows/backoffice.yaml`.

| Asset | SDK selection |
| --- | --- |
| `idle.png` | Default icon and fallback |
| `thinking.png` | Agent working on a turn without an active tool |
| `working.png` | Active tool without an application-specific pose rule |
| `casework.png` | Active tool belonging to `backoffice_api` |
| `error.png` | Failed tool or run |

The files use preserved-color rendering with `image_rendering: pixelated`.
They are static activity poses, not APNG loops. Tool mapping is by declared
MCP application; it does not distinguish reads, case creation or evaluation.
The SDK owns pose selection and authenticated image delivery. No application
code, new tools, Agent Card fields or extra access grants are needed.

All runtime images are square 512 × 512 RGBA PNGs, smaller than the platform's
512 KiB per-file limit. Keep these ordinary repository files alongside the
workflow when preparing a deployment. The platform reads them from the exact
repository event commit; a local edit alone does not publish the icon.

## Artwork provenance

The user approved the five-pose Casekeeper concept in this chat on 2026-10-20.
The built-in image generation tool isolated each approved pose on a transparent
background. Export sizing preserves that alpha channel and the complete square
canvas. The generation tool's original outputs remain outside the repository;
these PNGs are the deployment assets.

The extraction prompt used the following common instructions with the pose
description below:

> Use case: background-extraction. Edit target: the supplied approved Casekeeper
> contact sheet. Extract ONLY the character from the selected column. Preserve
> that exact approved character and pose, its pixel geometry, proportions,
> teal/ivory/navy palette, facial expression, papers, magnifying glass and any
> small pose-specific marks. No redesign. Remove ALL other characters, all text,
> headings, captions, dividers, footer, board background, and the ground shadow.
> Return ONE isolated production icon centered on a square 512 by 512 PNG with
> actual transparent alpha background, no checkerboard painted into the image,
> no frame, no text, no extra objects. Keep hard pixel-art edges. Keep the
> complete character, all extremities, and the dots or badge with a small clear
> margin. Keep the core folder body approximately 60 percent of the canvas
> width and feet baseline approximately 88 percent from the top so the poses
> will share a stable visual scale. The transparent spaces around arms and
> between feet must remain transparent.

Pose descriptions:

- Idle: first column; upright teal folder with navy eyes, ivory pages, tiny
  feet, magnifying glass lowered on the viewer's left.
- Thinking: second column; raised magnifying glass on the viewer's right near
  its face, three navy square thinking dots above.
- Working: third column; lifts an ivory page above its head on the viewer's
  right, navy motion ticks, magnifying glass lowered on the viewer's left.
- Casework: fourth column; inspects a document held in front with raised
  magnifying glass on the viewer's right, two small inspection ticks.
- Error: fifth column; slightly concerned eyes and eyebrows, magnifying glass
  lowered on the viewer's left, amber exclamation badge on the viewer's right.
