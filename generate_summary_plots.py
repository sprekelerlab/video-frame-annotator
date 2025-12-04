#!/usr/bin/env python3
"""
Generate summary plots showing frames around marked frames.

Creates montage plots with one row per trial, showing 3 frames before,
the marked frame, and 3 frames after the marked frame.

Plots are organized by the same folder structure as the source videos.
"""

import argparse
import cv2
import matplotlib

# Use non-interactive backend to avoid X11 errors in headless environments
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path


def extract_frame(video_path, frame_number):
    """
    Extract a specific frame from a video file.

    Parameters
    ----------
    video_path : str or Path
        Path to video file
    frame_number : int
        Frame number to extract (0-indexed)

    Returns
    -------
    numpy.ndarray or None
        Frame as BGR image array, or None if extraction failed
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    ret, frame = cap.read()
    cap.release()

    if ret:
        # Convert BGR to RGB for matplotlib
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return None


def find_video_file(trial_name, video_folder):
    """
    Find video file matching trial name.

    Parameters
    ----------
    trial_name : str
        Name of trial (filename without extension)
    video_folder : Path
        Root folder to search for videos

    Returns
    -------
    Path or None
        Path to video file if found
    """
    video_extensions = [".avi", ".mp4", ".mov", ".mkv"]
    for ext in video_extensions:
        for video_file in video_folder.rglob(f"{trial_name}{ext}"):
            if video_file.exists():
                return video_file
    return None


def create_summary_plot(
    group_name, trials_data, video_folder, output_path, frames_before=3, frames_after=3
):
    """
    Create a summary plot for one group of trials.

    Parameters
    ----------
    group_name : str
        Name/path of the group (e.g., "349/hab")
    trials_data : list of dict
        List of dicts with 'trial' and 'frame' keys
    video_folder : Path
        Root folder containing videos
    output_path : Path
        Where to save the plot
    frames_before : int, optional
        Number of frames before marked frame to show (default: 3)
    frames_after : int, optional
        Number of frames after marked frame to show (default: 3)
    """
    num_trials = len(trials_data)
    num_cols = frames_before + 1 + frames_after  # 7 total

    if num_trials == 0:
        print(f"No trials found for {group_name}")
        return

    # Create figure with black background
    fig, axes = plt.subplots(
        num_trials, num_cols, figsize=(num_cols * 2, num_trials * 2), facecolor="black"
    )
    fig.patch.set_facecolor("black")

    # Handle single trial case
    if num_trials == 1:
        axes = axes.reshape(1, -1)

    # Process each trial
    for row_idx, trial_data in enumerate(trials_data):
        trial_name = trial_data["trial"]
        marked_frame = trial_data["frame"]

        # Check if marked_frame is NaN (no frame selected)
        is_nan = pd.isna(marked_frame) or (isinstance(marked_frame, float) and np.isnan(marked_frame)) or str(marked_frame).lower() == "nan"

        # Find video file
        video_file = find_video_file(trial_name, video_folder)
        if not video_file:
            print(f"Warning: Video not found for trial {trial_name}")
            # Fill with black frames
            for col_idx in range(num_cols):
                axes[row_idx, col_idx].imshow(np.zeros((100, 100, 3), dtype=np.uint8))
                axes[row_idx, col_idx].axis("off")
                # Set trial name as ylabel on first column
                if col_idx == 0:
                    axes[row_idx, col_idx].set_ylabel(trial_name, color="white", fontsize=8, rotation=0, ha="right", va="center")
            continue

        # Get total frame count for equal spacing if no frame selected
        cap = cv2.VideoCapture(str(video_file))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        # Extract frames
        frame_images = []
        frame_numbers = []  # Track frame numbers for display
        
        if is_nan:
            # No frame selected: plot equally distanced frames
            # e.g., if 50 frames: 0, 10, 20, 30, 40, 50
            num_samples = num_cols
            if total_frames > 0:
                step = max(1, total_frames // (num_samples - 1)) if num_samples > 1 else total_frames
                frame_indices = [min(i * step, total_frames - 1) for i in range(num_samples)]
            else:
                frame_indices = [0] * num_samples
            
            for frame_idx in frame_indices:
                frame = extract_frame(video_file, frame_idx)
                if frame is None:
                    frame = np.zeros((100, 100, 3), dtype=np.uint8)
                frame_images.append(frame)
                frame_numbers.append(frame_idx)
        else:
            # Normal case: frames around marked frame
            # First column: first frame of video (frame 0)
            # Last column: last frame of video
            # Middle columns: frames around marked frame
            marked_frame_int = int(marked_frame)
            
            for col_idx in range(num_cols):
                if col_idx == 0:
                    # First column: first frame of video
                    target_frame = 0
                elif col_idx == num_cols - 1:
                    # Last column: last frame of video
                    target_frame = total_frames - 1
                else:
                    # Middle columns: frames around marked frame
                    # Calculate offset from marked frame
                    # Original layout had marked frame at frames_before, so offset = col_idx - frames_before
                    offset = col_idx - frames_before
                    target_frame = max(0, min(marked_frame_int + offset, total_frames - 1))
                
                frame = extract_frame(video_file, target_frame)
                if frame is None:
                    frame = np.zeros((100, 100, 3), dtype=np.uint8)
                frame_images.append(frame)
                frame_numbers.append(target_frame)

        # Display frames
        for col_idx, (frame_img, frame_num) in enumerate(zip(frame_images, frame_numbers)):
            ax = axes[row_idx, col_idx]
            ax.imshow(frame_img)
            ax.axis("off")

            # Set trial name as ylabel on first column (small font)
            if col_idx == 0:
                ax.set_ylabel(trial_name, color="white", fontsize=8, rotation=0, ha="right", va="center")

            # Set frame number as title (only on first row to avoid repetition)
            if row_idx == 0:
                frame_num_int = int(frame_num)
                if not is_nan and col_idx == frames_before:
                    ax.set_title(f"Frame {frame_num_int}", color="red", fontsize=10, weight="bold")
                else:
                    ax.set_title(f"Frame {frame_num_int}", color="white", fontsize=10)

            # Highlight marked frame (at frames_before column) - only if not NaN
            if not is_nan and col_idx == frames_before:
                # Add red border
                for spine in ax.spines.values():
                    spine.set_edgecolor("red")
                    spine.set_linewidth(3)

    # Add title (use group name which mirrors folder structure)
    display_name = group_name.replace("/", " / ").replace("\\", " / ")
    fig.suptitle(
        f"{display_name}\n(Red border = marked frame, No red = no frame selected)",
        color="white",
        fontsize=14,
        y=0.995,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.98])
    plt.savefig(output_path, facecolor="black", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Created plot: {output_path}")


def generate_all_plots(output_dir, video_folder, frames_before=3, frames_after=3):
    """
    Generate summary plots for all groups (mirroring source folder structure).

    Parameters
    ----------
    output_dir : Path
        Output directory containing results.csv
    video_folder : Path
        Root folder containing videos
    frames_before : int, optional
        Number of frames before marked frame (default: 3)
    frames_after : int, optional
        Number of frames after marked frame (default: 3)
    """
    results_csv = output_dir / "results.csv"
    if not results_csv.exists():
        raise ValueError(f"results.csv not found: {results_csv}")

    df = pd.read_csv(results_csv)

    # Check if 'group' column exists (new format)
    if "group" not in df.columns:
        # Fallback for old format with animal/session columns
        if "animal" in df.columns and "session" in df.columns:
            df["group"] = df["animal"].astype(str) + "/" + df["session"].astype(str)
        else:
            # No grouping info, put all in one plot
            df["group"] = "all"

    # Create summary_plots directory
    plots_dir = output_dir / "summary_plots"
    plots_dir.mkdir(exist_ok=True)

    # Group by the group column (mirrors source folder structure)
    grouped = df.groupby("group")

    for group_name, group in grouped:
        # Convert frame column to numeric, keeping NaN values
        group = group.copy()
        group["frame"] = pd.to_numeric(group["frame"], errors="coerce")
        trials_data = group[["trial", "frame"]].to_dict("records")

        # Create output path mirroring the group structure
        # e.g., group "349/hab" -> "summary_plots/349/hab.png"
        # Handle "." or empty group (files in root)
        if group_name in [".", "", "unknown"]:
            output_path = plots_dir / "all_trials.png"
        else:
            # Convert group path to output filename
            # "349/hab" -> "349_hab.png" or nested "349/hab.png"
            group_path = Path(group_name)
            output_subdir = plots_dir / group_path.parent
            output_subdir.mkdir(parents=True, exist_ok=True)
            output_path = output_subdir / f"{group_path.name}.png"

        create_summary_plot(
            group_name, trials_data, video_folder, output_path, frames_before, frames_after
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate summary plots from annotation results")
    parser.add_argument("output_dir", help="Path to output directory containing results.csv")
    parser.add_argument(
        "--video-folder",
        required=True,
        help="Path to root video folder (same as used for scoring)",
    )
    parser.add_argument(
        "--frames-before",
        type=int,
        default=3,
        help="Number of frames before marked frame to show (default: 3)",
    )
    parser.add_argument(
        "--frames-after",
        type=int,
        default=3,
        help="Number of frames after marked frame to show (default: 3)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    video_folder = Path(args.video_folder)

    if not video_folder.exists():
        raise ValueError(f"Video folder not found: {video_folder}")

    generate_all_plots(output_dir, video_folder, args.frames_before, args.frames_after)
    print("Summary plots generation complete!")


if __name__ == "__main__":
    main()
