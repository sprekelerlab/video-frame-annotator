#!/usr/bin/env python3
"""
Merge individual trial annotation files into a single CSV.

Reads all .txt files from per_trial/ directory and merges them into results.csv.
"""

import argparse
import pandas as pd
from datetime import datetime
from pathlib import Path


def merge_annotations(output_dir, video_folder=None):
    """
    Merge individual trial annotations into CSV.

    Parameters
    ----------
    output_dir : str or Path
        Path to output directory containing per_trial/ folder
    video_folder : str or Path, optional
        Path to video folder to extract relative paths from
    """
    output_dir = Path(output_dir)
    per_trial_dir = output_dir / "per_trial"

    if not per_trial_dir.exists():
        raise ValueError(f"per_trial directory not found: {per_trial_dir}")

    # Build video lookup if video folder provided
    video_lookup = {}
    if video_folder:
        video_folder = Path(video_folder)
        video_extensions = [".avi", ".mp4", ".mov", ".mkv"]
        for ext in video_extensions:
            for video in video_folder.rglob(f"*{ext}"):
                video_lookup[video.stem] = video

    results = []
    for txt_file in sorted(per_trial_dir.glob("*.txt")):
        trial_name = txt_file.stem
        with open(txt_file, "r") as f:
            frame = int(f.read().strip())

        # Get relative path from video folder (for generic folder structure)
        relative_path = ""
        video_path = video_lookup.get(trial_name)
        if video_path and video_folder:
            try:
                relative_path = str(video_path.relative_to(video_folder))
            except ValueError:
                relative_path = str(video_path)

        # Extract group key (parent directory path without filename)
        # e.g., "349/hab/trial.avi" -> "349/hab"
        group_key = str(Path(relative_path).parent) if relative_path else "unknown"

        # Get scorer name from output directory name
        scorer = output_dir.name

        results.append(
            {
                "trial": trial_name,
                "frame": frame,
                "relative_path": relative_path,
                "group": group_key,
                "scorer": scorer,
                "timestamp": datetime.now().isoformat(),
            }
        )

    df = pd.DataFrame(results)
    df = df.sort_values("trial")
    output_csv = output_dir / "results.csv"
    df.to_csv(output_csv, index=False)
    print(f"Merged {len(results)} annotations to {output_csv}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Merge trial annotations into CSV")
    parser.add_argument("output_dir", help="Path to output directory")
    parser.add_argument(
        "--video-folder",
        help="Path to video folder (for extracting relative paths)",
    )

    args = parser.parse_args()
    merge_annotations(args.output_dir, args.video_folder)


if __name__ == "__main__":
    main()
