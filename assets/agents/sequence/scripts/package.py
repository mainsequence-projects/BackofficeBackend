import hashlib
import json
from pathlib import Path

from optimize_png import optimize_png
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
INPUTS = json.loads((ROOT / "inputs.json").read_text())
STATES = ("idle", "thinking", "working", "error")
THEMES = ("neutral",)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    catalog = {
        "schema": 1,
        "status": "repository-owned workflow assets",
        "rendering": "color",
        "imageRendering": "auto",
        "themeSelection": "neutral ink for light and dark backgrounds",
        "agents": [],
    }
    for agent in INPUTS:
        item = {k: agent[k] for k in ("key", "name", "action")}
        item["variants"] = {}
        item["identities"] = {}
        for theme in THEMES:
            variants = item["variants"][theme] = {}
            target = ROOT / "assets" / agent["key"] / theme
            target.mkdir(parents=True, exist_ok=True)
            identity = target / "identity.png"
            identity.write_bytes(
                (ROOT / "build" / "frames" / theme / agent["key"] / "identity.png").read_bytes()
            )
            item["identities"][theme] = {
                "file": str(identity.relative_to(ROOT)),
                "sha256": sha(identity),
            }
            for state in STATES:
                inputs = sorted(
                    (ROOT / "build" / "frames" / theme / agent["key"]).glob(f"{state}-*.png")
                )
                assert len(inputs) == 60, (agent["key"], theme, state, len(inputs))
                frames = [Image.open(p).convert("RGBA") for p in inputs]
                animated, still = target / f"{state}.png", target / f"{state}-still.png"
                frames[0].save(
                    animated,
                    save_all=True,
                    append_images=frames[1:],
                    duration=80,
                    loop=0,
                    optimize=True,
                )
                optimize_png(animated)
                frames[0].save(still, optimize=True)
                with Image.open(animated) as image:
                    durations = []
                    for i in range(image.n_frames):
                        image.seek(i)
                        durations.append(image.info["duration"])
                    record = {
                        "animated": str(animated.relative_to(ROOT)),
                        "still": str(still.relative_to(ROOT)),
                        "width": image.width,
                        "height": image.height,
                        "frames": image.n_frames,
                        "frameDurationsMs": durations,
                        "cycleDurationMs": sum(durations),
                        "bytes": animated.stat().st_size,
                        "sha256": sha(animated),
                        "stillSha256": sha(still),
                    }
                variants[state] = record
        catalog["agents"].append(item)
    (ROOT / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    from verify import verify

    print(json.dumps(verify(), indent=2))


if __name__ == "__main__":
    main()
