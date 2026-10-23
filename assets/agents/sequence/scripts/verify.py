import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent


def verify():
    catalog = json.loads((ROOT / "catalog.json").read_text())
    inputs = json.loads((ROOT / "inputs.json").read_text())
    assert len(catalog["agents"]) == 1
    assert {a["key"] for a in inputs} == {a["key"] for a in catalog["agents"]}
    for source in inputs:
        assert hashlib.sha256((ROOT / source["file"]).read_bytes()).hexdigest() == source["sha256"]
    count, max_bytes = 0, 0
    for agent in catalog["agents"]:
        assert set(agent["variants"]) == {"neutral"}
        for theme, states in agent["variants"].items():
            assert set(states) == {"idle", "thinking", "working", "error"}
            identity_path = ROOT / agent["identities"][theme]["file"]
            assert (
                hashlib.sha256(identity_path.read_bytes()).hexdigest()
                == agent["identities"][theme]["sha256"]
            )
            identity = Image.open(identity_path).convert("RGBA")
            identity_mask = identity.getchannel("A").point(lambda x: 255 if x else 0)
            for state, asset in states.items():
                name = f"{agent['key']}/{theme}/{state}"
                path = ROOT / asset["animated"]
                assert path.stat().st_size <= 65536, (name, path.stat().st_size)
                assert path.stat().st_size == asset["bytes"], name
                assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"], name
                assert (
                    hashlib.sha256((ROOT / asset["still"]).read_bytes()).hexdigest()
                    == asset["stillSha256"]
                ), name
                with Image.open(path) as image:
                    assert image.format == "PNG" and image.is_animated, name
                    assert image.width == image.height == 128, name
                    assert 1 < image.n_frames <= 120, name
                    assert image.n_frames == asset["frames"], name
                    assert image.n_frames * image.width * image.height <= 4194304, name
                    assert image.info["loop"] == 0, name
                    frames, durations = [], []
                    for i in range(image.n_frames):
                        image.seek(i)
                        frames.append(image.convert("RGBA"))
                        durations.append(image.info["duration"])
                    assert min(durations) >= 20 and sum(durations) == 4800, (name, durations)
                    assert durations == asset["frameDurationsMs"], name
                    assert sum(durations) == asset["cycleDurationMs"], name
                still = Image.open(ROOT / asset["still"]).convert("RGBA")
                assert ImageChops.difference(frames[0], still).getbbox(alpha_only=False) is None, (
                    name
                )
                assert any(
                    ImageChops.difference(frames[0], f).getbbox(alpha_only=False)
                    for f in frames[1:]
                ), name
                rendered = sorted(
                    (ROOT / "build" / "frames" / theme / agent["key"]).glob(f"{state}-*.png")
                )
                if rendered:
                    # Pillow coalesces identical adjacent frames and retains their total duration.
                    expanded = []
                    for frame, duration in zip(frames, durations, strict=True):
                        assert duration % 80 == 0, (name, duration)
                        expanded.extend([frame] * int(duration / 80))
                    assert len(rendered) == len(expanded) == 60, name
                    for frame, source_frame in zip(expanded, rendered, strict=True):
                        expected = Image.open(source_frame).convert("RGBA")
                        assert (
                            ImageChops.difference(expected, frame).getbbox(alpha_only=False) is None
                        ), name
                # Check all original logo pixels, including transparent anti-aliased edges.
                for frame in frames:
                    under_logo = Image.composite(frame, identity, identity_mask)
                    assert (
                        ImageChops.difference(identity, under_logo).getbbox(alpha_only=False)
                        is None
                    ), name
                    bounds = frame.getchannel("A").getbbox()
                    assert bounds and min(bounds[:2]) > 0 and max(bounds[2:]) < 128, (name, bounds)
                max_bytes = max(max_bytes, path.stat().st_size)
                count += 1
    assert count == 4
    return {
        "agents": 1,
        "animatedAssets": count,
        "stills": count,
        "themes": ["neutral"],
        "states": ["idle", "thinking", "working", "error"],
        "largestAssetBytes": max_bytes,
        "sourcesUnchanged": True,
        "allAnimate": True,
        "noClipping": True,
        "logoPixelsStable": True,
        "firstFrameStillsMatch": True,
        "platformAssetLimits": "pass",
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
