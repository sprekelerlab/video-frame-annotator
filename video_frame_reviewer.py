#!/usr/bin/env python3
"""
Video Frame Reviewer GUI

A tool for manually annotating the first "threat detection" frame in behavioral videos.
Uses MPV for smooth, frame-accurate video playback.
"""

import argparse
import json
import os
import random
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import mpv
except ImportError:
    print("Error: python-mpv not installed. Install with: conda install -c conda-forge python-mpv")
    sys.exit(1)


class VideoFrameReviewer:
    """Main application class for video frame reviewing."""

    def __init__(self, input_folder, output_name, description="", blind_mode=True, continue_session=None):
        """
        Initialize the video frame reviewer.

        Parameters
        ----------
        input_folder : str
            Path to folder containing videos (e.g., facial_expression folder)
        output_name : str
            Name for output folder
        description : str, optional
            Description of the scoring session
        blind_mode : bool, optional
            If True, hide trial information from reviewer (default: True)
        continue_session : str, optional
            Path to existing output folder to continue from
        """
        self.input_folder = Path(input_folder) if input_folder else None
        self.output_name = output_name
        self.description = description
        self.blind_mode = blind_mode
        self.continue_session = continue_session

        # Setup output directory
        if continue_session:
            self.output_dir = Path(continue_session)
            self._load_config()
        else:
            self.output_dir = Path(output_name)
            self.output_dir.mkdir(exist_ok=True)
            self.per_trial_dir = self.output_dir / "per_trial"
            self.per_trial_dir.mkdir(exist_ok=True)
            self._save_config()
            self._create_readme()

        # Find all videos
        self.videos = self._find_videos()
        if not self.videos:
            raise ValueError(f"No videos found in {self.input_folder}")

        # Filter already-scored videos
        self.videos = self._filter_scored_videos()
        if not self.videos:
            messagebox.showinfo("Complete", "All videos have already been scored!")
            sys.exit(0)

        # Randomize order
        random.shuffle(self.videos)

        # Current state
        self.current_idx = 0
        self.current_video = None
        self.current_frame = 0
        self.player = None

        # Setup GUI
        self.root = tk.Tk()
        self.root.title("Video Frame Reviewer")
        self.root.geometry("400x200")
        self.root.configure(bg="black")

        # Create info display
        self._create_gui()

        # Bind keyboard shortcuts (DE/EN keyboard compatible)
        self.root.bind("<space>", lambda e: self._toggle_play())
        self.root.bind("<Return>", lambda e: self._mark_frame())
        # Arrow keys: Left/Right for frame stepping, Shift+Left/Right for seeking
        self.root.bind("<Left>", lambda e: self._frame_step_backward())
        self.root.bind("<Right>", lambda e: self._frame_step_forward())
        self.root.bind("<Shift-Left>", lambda e: self._seek_backward())
        self.root.bind("<Shift-Right>", lambda e: self._seek_forward())
        # Up/Down for speed control
        self.root.bind("<Up>", lambda e: self._increase_speed())
        self.root.bind("<Down>", lambda e: self._decrease_speed())
        self.root.bind("q", lambda e: self._quit())

        # Focus on root window to capture keyboard events
        self.root.focus_set()

        # Load first video
        self._load_video()

    def _find_videos(self):
        """Find all video files recursively in input folder."""
        if not self.input_folder or not self.input_folder.exists():
            return []

        video_extensions = {".avi", ".mp4", ".mov", ".mkv"}
        videos = []
        for ext in video_extensions:
            videos.extend(self.input_folder.rglob(f"*{ext}"))

        # Sort for reproducibility before randomization
        return sorted(videos)

    def _filter_scored_videos(self):
        """Filter out videos that have already been scored."""
        scored_trials = set()
        if self.per_trial_dir.exists():
            for txt_file in self.per_trial_dir.glob("*.txt"):
                scored_trials.add(txt_file.stem)

        # Extract trial name from video path (filename without extension)
        remaining = []
        for video in self.videos:
            trial_name = video.stem
            if trial_name not in scored_trials:
                remaining.append(video)

        return remaining

    def _save_config(self):
        """Save configuration to config.json."""
        config = {
            "input_folder": str(self.input_folder) if self.input_folder else None,
            "blind_mode": self.blind_mode,
            "description": self.description,
        }
        with open(self.output_dir / "config.json", "w") as f:
            json.dump(config, f, indent=2)

    def _load_config(self):
        """Load configuration from existing session."""
        config_path = self.output_dir / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
            self.input_folder = Path(config["input_folder"]) if config.get("input_folder") else None
            self.blind_mode = config.get("blind_mode", True)
            self.description = config.get("description", "")
        else:
            raise ValueError(f"config.json not found in {self.output_dir}")

        self.per_trial_dir = self.output_dir / "per_trial"
        self.per_trial_dir.mkdir(exist_ok=True)

        # Create README if it doesn't exist
        readme_path = self.output_dir / "README.md"
        if not readme_path.exists():
            self._create_readme()

    def _create_readme(self):
        """Create README.md in output directory."""
        readme_content = f"""# Video Frame Review Session: {self.output_name}

## Description
{self.description if self.description else "No description provided."}

## Configuration
- Input folder: {self.input_folder}
- Blind mode: {self.blind_mode}
- Created: {Path(self.output_dir).stat().st_mtime}

## Results
- Individual trial annotations: `per_trial/`
- Merged results: `results.csv`
- Summary plots: `summary_plots/` (if generated)
"""
        with open(self.output_dir / "README.md", "w") as f:
            f.write(readme_content)

    def _create_gui(self):
        """Create the GUI elements."""
        # Progress label
        self.progress_label = tk.Label(
            self.root,
            text="",
            bg="black",
            fg="white",
            font=("Arial", 14, "bold"),
        )
        self.progress_label.pack(pady=10)

        # Frame number label
        self.frame_label = tk.Label(
            self.root,
            text="Frame: 0",
            bg="black",
            fg="yellow",
            font=("Arial", 12),
        )
        self.frame_label.pack(pady=5)

        # Video info label (only if not blind mode)
        self.video_info_label = tk.Label(
            self.root,
            text="",
            bg="black",
            fg="gray",
            font=("Arial", 10),
        )
        if not self.blind_mode:
            self.video_info_label.pack(pady=5)

        # Instructions label
        instructions = (
            "Space: Play/Pause | Enter: Mark frame & next | "
            "Left/Right: Frame step | Shift+Left/Right: Seek | Up/Down: Speed | Q: Quit"
        )
        self.instructions_label = tk.Label(
            self.root,
            text=instructions,
            bg="black",
            fg="lightgray",
            font=("Arial", 9),
            wraplength=380,
        )
        self.instructions_label.pack(pady=10)

        # Update progress display
        self._update_progress()

    def _update_progress(self):
        """Update progress display."""
        total = len(self.videos)
        current = self.current_idx + 1
        self.progress_label.config(text=f"Video {current}/{total}")

    def _update_frame_display(self):
        """Update frame number display."""
        if self.player:
            try:
                # Get current time position and FPS to calculate frame
                time_pos = self.player.time_pos
                fps = self.player.fps
                if time_pos is not None and fps is not None:
                    frame = int(time_pos * fps)
                    self.current_frame = frame
                    self.frame_label.config(text=f"Frame: {frame}")
            except (AttributeError, KeyError, TypeError, ValueError):
                pass

    def _load_video(self):
        """Load the current video in MPV."""
        if self.current_idx >= len(self.videos):
            self._finish_session()
            return

        self.current_video = self.videos[self.current_idx]

        # Update video info if not blind mode
        if not self.blind_mode:
            # Try to extract animal/session from path
            parts = self.current_video.parts
            animal = None
            session = None
            try:
                # Try different possible folder names
                for folder_name in ["facial_expression", "body_posture", "pupil"]:
                    if folder_name in parts:
                        animal_idx = parts.index(folder_name) + 1
                        if animal_idx < len(parts) - 2:
                            animal = parts[animal_idx]
                            session = parts[animal_idx + 1]
                            break
                if animal and session:
                    self.video_info_label.config(text=f"Animal: {animal} | Session: {session}")
                else:
                    self.video_info_label.config(text=str(self.current_video.name))
            except (ValueError, IndexError):
                self.video_info_label.config(text=str(self.current_video.name))

        # Create MPV player
        if self.player:
            self.player.terminate()

        self.player = mpv.MPV(
            input_default_bindings=True,
            input_vo_keyboard=True,
        )

        # Register property observer for frame updates
        @self.player.property_observer("time-pos")
        def time_observer(_name, value):
            if value is not None:
                self.root.after(0, self._update_frame_display)

        # Load video file
        self.player.play(str(self.current_video))
        self.player.pause = True  # Start paused

        # Update display
        self._update_progress()
        self._update_frame_display()

    def _toggle_play(self):
        """Toggle play/pause."""
        if self.player:
            self.player.pause = not self.player.pause

    def _seek_backward(self):
        """Seek backward 5 seconds."""
        if self.player:
            current_time = self.player.time_pos or 0
            self.player.time_pos = max(0, current_time - 5)

    def _seek_forward(self):
        """Seek forward 5 seconds."""
        if self.player:
            current_time = self.player.time_pos or 0
            duration = self.player.duration or 0
            self.player.time_pos = min(duration, current_time + 5)

    def _frame_step_backward(self):
        """Step one frame backward."""
        if self.player:
            try:
                # Get current time and FPS
                current_time = self.player.time_pos
                fps = self.player.fps
                if current_time is not None and fps is not None and fps > 0:
                    # Calculate frame duration
                    frame_duration = 1.0 / fps
                    # Seek backward by one frame using command interface
                    new_time = max(0, current_time - frame_duration)
                    # Use command for frame-accurate seeking
                    self.player.command("seek", new_time, "absolute", "exact")
            except (AttributeError, KeyError, TypeError, ValueError, Exception):
                # Fallback: adjust time_pos directly (less accurate but more compatible)
                try:
                    current_time = self.player.time_pos or 0
                    fps = self.player.fps or 30.0
                    frame_duration = 1.0 / fps
                    self.player.time_pos = max(0, current_time - frame_duration)
                except:
                    pass

    def _frame_step_forward(self):
        """Step one frame forward."""
        if self.player:
            try:
                # Get current time and FPS
                current_time = self.player.time_pos
                fps = self.player.fps
                duration = self.player.duration
                if current_time is not None and fps is not None and fps > 0:
                    # Calculate frame duration
                    frame_duration = 1.0 / fps
                    # Seek forward by one frame using command interface
                    new_time = current_time + frame_duration
                    if duration is not None:
                        new_time = min(duration, new_time)
                    # Use command for frame-accurate seeking
                    self.player.command("seek", new_time, "absolute", "exact")
            except (AttributeError, KeyError, TypeError, ValueError, Exception):
                # Fallback: adjust time_pos directly (less accurate but more compatible)
                try:
                    current_time = self.player.time_pos or 0
                    fps = self.player.fps or 30.0
                    duration = self.player.duration
                    frame_duration = 1.0 / fps
                    new_time = current_time + frame_duration
                    if duration is not None:
                        new_time = min(duration, new_time)
                    self.player.time_pos = new_time
                except:
                    pass

    def _decrease_speed(self):
        """Decrease playback speed."""
        if self.player:
            current_speed = self.player.speed or 1.0
            new_speed = max(0.25, current_speed - 0.25)
            self.player.speed = new_speed

    def _increase_speed(self):
        """Increase playback speed."""
        if self.player:
            current_speed = self.player.speed or 1.0
            new_speed = min(2.0, current_speed + 0.25)
            self.player.speed = new_speed

    def _mark_frame(self):
        """Mark current frame and advance to next video."""
        if not self.player:
            return

        # Get current frame number from time position and FPS
        try:
            # Use the stored current_frame if available (more accurate from frame stepping)
            if hasattr(self, 'current_frame') and self.current_frame is not None:
                frame = self.current_frame
            else:
                # Fallback to time-based calculation
                time_pos = self.player.time_pos or 0
                fps = self.player.fps or 30
                frame = int(time_pos * fps)
        except (AttributeError, KeyError, TypeError, ValueError):
            frame = self.current_frame if hasattr(self, 'current_frame') else 0

        # Save frame number to file
        trial_name = self.current_video.stem
        output_file = self.per_trial_dir / f"{trial_name}.txt"
        with open(output_file, "w") as f:
            f.write(str(frame))

        # Advance to next video
        self.current_idx += 1
        if self.current_idx < len(self.videos):
            self._load_video()
        else:
            self._finish_session()

    def _finish_session(self):
        """Handle session completion."""
        if self.player:
            self.player.terminate()

        # Merge annotations
        self._merge_annotations()

        # Ask about summary plots
        response = messagebox.askyesno(
            "Session Complete",
            f"All {len(self.videos)} videos have been scored!\n\n"
            "Would you like to generate summary plots?\n"
            "(This may take a few moments)",
        )

        if response:
            self._generate_summary_plots()

        messagebox.showinfo("Complete", "Session complete! Results saved.")
        self.root.quit()

    def _merge_annotations(self):
        """Merge individual txt files into CSV."""
        import pandas as pd
        from datetime import datetime

        # Build a lookup from trial name to video path
        video_lookup = {}
        if self.input_folder:
            video_extensions = {".avi", ".mp4", ".mov", ".mkv"}
            for ext in video_extensions:
                for video in self.input_folder.rglob(f"*{ext}"):
                    video_lookup[video.stem] = video

        results = []
        for txt_file in sorted(self.per_trial_dir.glob("*.txt")):
            trial_name = txt_file.stem
            with open(txt_file, "r") as f:
                frame = int(f.read().strip())

            # Get relative path from input folder (for generic folder structure)
            relative_path = ""
            video_path = video_lookup.get(trial_name)
            if video_path and self.input_folder:
                try:
                    relative_path = str(video_path.relative_to(self.input_folder))
                except ValueError:
                    relative_path = str(video_path)

            # Extract group key (parent directory path without filename)
            # e.g., "349/hab/trial.avi" -> "349/hab"
            group_key = str(Path(relative_path).parent) if relative_path else "unknown"

            results.append(
                {
                    "trial": trial_name,
                    "frame": frame,
                    "relative_path": relative_path,
                    "group": group_key,
                    "scorer": self.output_name,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        df = pd.DataFrame(results)
        df = df.sort_values("trial")
        df.to_csv(self.output_dir / "results.csv", index=False)

    def _generate_summary_plots(self):
        """Generate summary plots using the separate script."""
        import subprocess

        if not self.input_folder or not self.input_folder.exists():
            messagebox.showerror(
                "Error",
                "Cannot generate summary plots: video folder not found. "
                "Please run generate_summary_plots.py manually with --video-folder argument.",
            )
            return

        script_path = Path(__file__).parent / "generate_summary_plots.py"
        if script_path.exists():
            try:
                subprocess.run(
                    [
                        sys.executable,
                        str(script_path),
                        str(self.output_dir),
                        "--video-folder",
                        str(self.input_folder),
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                messagebox.showerror("Error", f"Failed to generate summary plots: {e}")
        else:
            messagebox.showwarning(
                "Warning",
                "generate_summary_plots.py not found. Please run it manually.",
            )

    def _quit(self):
        """Quit the application."""
        if self.player:
            self.player.terminate()
        self.root.quit()

    def run(self):
        """Start the GUI main loop."""
        self.root.mainloop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Video Frame Reviewer - Manual annotation tool for threat detection frames"
    )
    parser.add_argument(
        "input_folder",
        nargs="?",
        help="Path to folder containing videos (e.g., resources/nextcloud/facial_expression)",
    )
    parser.add_argument("--name", required=True, help="Name for output folder")
    parser.add_argument("--description", default="", help="Description of scoring session")
    parser.add_argument(
        "--show-trial-info",
        action="store_true",
        help="Show trial information (animal, session) during review",
    )
    parser.add_argument(
        "--continue",
        dest="continue_session",
        help="Continue from existing output folder",
    )

    args = parser.parse_args()

    # Handle continue session
    if args.continue_session:
        if not Path(args.continue_session).exists():
            print(f"Error: Output folder not found: {args.continue_session}")
            sys.exit(1)
        input_folder = None  # Will be loaded from config
    else:
        input_folder = args.input_folder
        if not input_folder:
            # Open file dialog
            root = tk.Tk()
            root.withdraw()
            input_folder = filedialog.askdirectory(title="Select video folder")
            root.destroy()
            if not input_folder:
                print("No folder selected. Exiting.")
                sys.exit(1)

    # Create and run reviewer
    try:
        reviewer = VideoFrameReviewer(
            input_folder=input_folder,
            output_name=args.name,
            description=args.description,
            blind_mode=not args.show_trial_info,
            continue_session=args.continue_session,
        )
        reviewer.run()
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()

