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

    def __init__(self, input_folder, output_name, description="", blind_mode=True, continue_session=None, fps=None):
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
        fps : float, optional
            Override FPS (default: auto-detect from video container metadata)
        """
        self.input_folder = Path(input_folder) if input_folder else None
        self.output_name = output_name
        self.description = description
        self.blind_mode = blind_mode
        self.continue_session = continue_session
        self.fps_override = fps

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
        # Set larger initial size to accommodate embedded video
        self.root.geometry("1200x800")
        self.root.configure(bg="black")
        
        # Video container frame for MPV embedding
        self.video_frame = None

        # Create info display
        self._create_gui()

        # Bind Enter and ESC using bind_all to catch them even when MPV has focus
        # Return "break" to prevent MPV from processing these keys
        def handle_enter(event):
            self._mark_frame()
            return "break"
        
        def handle_esc(event):
            self._mark_no_frame()
            return "break"
        
        def handle_ctrl_left(event):
            # Ctrl+Left: go to previous video
            if self.current_idx > 0:
                self.current_idx -= 1
                self._load_video()
            return "break"
        
        def handle_ctrl_right(event):
            # Ctrl+Right: go to next video
            if self.current_idx < len(self.videos) - 1:
                self.current_idx += 1
                self._load_video()
            return "break"
        
        self.root.bind_all("<Return>", handle_enter)
        self.root.bind_all("<KP_Enter>", handle_enter)
        self.root.bind_all("<Escape>", handle_esc)
        # Ctrl+Left/Right for video navigation
        self.root.bind_all("<Control-Left>", handle_ctrl_left)
        self.root.bind_all("<Control-Right>", handle_ctrl_right)
        
        # Keep root window focused so we can intercept Enter/ESC/Tab
        self.root.focus_set()
        
        # When clicking video area, keep root focused so we can intercept keys
        self.video_frame.bind("<Button-1>", lambda e: self.root.focus_set())

        # Ensure window is fully realized before loading video (needed for window embedding)
        self.root.update_idletasks()
        self.root.update()

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
        # Top frame for info
        top_frame = tk.Frame(self.root, bg="black")
        top_frame.pack(fill=tk.X, pady=5)

        # Progress label
        self.progress_label = tk.Label(
            top_frame,
            text="",
            bg="black",
            fg="white",
        )
        self.progress_label.pack(side=tk.LEFT, padx=10)

        # Instructions label (moved to top)
        instructions = (
            "Enter: Mark first threat frame | ESC: Skip (no threat detected) | "
            "Ctrl+Left/Right: Navigate videos | "
            "[/]: Speed | ,/.: Frame step | Left/Right: Seek"
        )
        self.instructions_label = tk.Label(
            top_frame,
            text=instructions,
            bg="black",
            fg="lightgray",
            wraplength=1180,
        )
        self.instructions_label.pack(side=tk.LEFT, padx=10)

        # Video info label (only if not blind mode)
        self.video_info_label = tk.Label(
            top_frame,
            text="",
            bg="black",
            fg="gray",
        )
        if not self.blind_mode:
            self.video_info_label.pack(side=tk.LEFT, padx=10)

        # Video container frame for MPV embedding
        self.video_frame = tk.Frame(self.root, bg="black", highlightthickness=0)
        self.video_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Update progress display
        self._update_progress()


    def _update_progress(self):
        """Update progress display."""
        total = len(self.videos)
        current = self.current_idx + 1
        self.progress_label.config(text=f"Video {current}/{total}")

    def _get_fps(self):
        """
        Get FPS for current video.
        
        Returns the user-provided FPS override if set, otherwise attempts to get
        container FPS via expand-text command. Returns None if unavailable.
        """
        if self.fps_override is not None:
            return self.fps_override
        if self.player:
            # Use expand-text to get container-fps (get_property doesn't work)
            try:
                fps_str = self.player.command('expand-text', '${container-fps}')
                if fps_str:
                    fps = float(fps_str)
                    if fps > 0:
                        return fps
            except (AttributeError, TypeError, ValueError, Exception):
                pass
        
        return None  # No default fallback - return None if unavailable


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

        # Get window ID for embedding (platform-specific)
        wid = None
        if sys.platform.startswith('linux'):
            # Linux/X11: use X11 window ID
            try:
                # Wait for video frame to be realized
                self.root.update_idletasks()
                wid = self.video_frame.winfo_id()
            except:
                pass
        elif sys.platform == 'win32':
            # Windows: use HWND
            try:
                self.root.update_idletasks()
                wid = self.video_frame.winfo_id()
            except:
                pass
        elif sys.platform == 'darwin':
            # macOS: use NSView (requires special handling)
            try:
                self.root.update_idletasks()
                # On macOS, we need to use the view's pointer
                # This is more complex and may require additional setup
                pass
            except:
                pass

        # Create MPV with window embedding if possible
        # Enable MPV's built-in GUI (OSC) and keyboard input for speed display
        mpv_options = {
            'input_default_bindings': True,  # Enable MPV's default keyboard bindings
            'input_vo_keyboard': True,  # Allow keyboard input to MPV
            'osc': True,  # Enable on-screen controller (shows speed, time, etc.)
            'script_opts': 'osc-visibility=always',  # Keep OSC always visible
            # OSD status message (always visible like Shift+O)
            'osd_level': 3,  # Always show OSD status message
            'osd_status_msg': '${playback-time/full} / ${duration} (${percent-pos}%)\nframe: ${estimated-frame-number} / ${estimated-frame-count}',
            # Optimize for frame-accurate stepping (especially backward)
            'hr-seek': 'yes',  # Enable high-resolution seeking for better backward stepping
            'hr-seek-framedrop': 'no',  # Don't drop frames during seeks (better accuracy)
            'video-sync': 'display-resample',  # Better frame accuracy
            'demuxer-readahead-secs': 30,  # Pre-buffer more frames (increased for backward stepping)
            'cache': 'yes',  # Enable caching for faster seeks
            'demuxer-max-bytes': '2GiB',  # Increase forward buffer size significantly
            'demuxer-max-back-bytes': '2GiB',  # Increase backward buffer significantly for backward stepping
            'demuxer-thread': 'yes',  # Use threading for demuxer (can help with backward)
            'demuxer-cache-wait': 'yes',  # Wait for cache when seeking (helps maintain buffer)
            # Try to keep more data in memory for backward stepping
            'cache-secs': 30,  # Keep 30 seconds of video in cache
            'cache-on-disk': 'no',  # Keep cache in memory (faster but uses more RAM)
        }
        
        if wid is not None:
            # Embed MPV in the Tkinter frame
            mpv_options['wid'] = str(wid)
            # Use X11 video output on Linux for embedding
            # Note: x11 is needed for window embedding, but we can suppress the warning
            if sys.platform.startswith('linux'):
                mpv_options['vo'] = 'x11'
                # Suppress x11 VO warning by setting log level
                mpv_options['msg-level'] = 'vo/x11=error'  # Only show errors, not warnings

        # Create MPV player - handle OSC gracefully if not available
        try:
            self.player = mpv.MPV(**mpv_options)
        except (AttributeError, TypeError, ValueError) as e:
            # OSC or script_opts not available, try without script_opts
            mpv_options.pop('script_opts', None)
            try:
                self.player = mpv.MPV(**mpv_options)
            except (AttributeError, TypeError, ValueError):
                # OSC not available, create without it
                mpv_options.pop('osc', None)
                self.player = mpv.MPV(**mpv_options)
        
        # Ensure Shift+O works to show progress/time (if not already bound)
        try:
            # Try to bind Shift+O to show-progress command
            self.player.command("keybind", "Shift+O", "show-progress")
        except Exception:
            # If binding fails, that's okay - Shift+O might already be bound by default
            pass
        
        # Use MPV's key press callbacks to intercept Enter/ESC/Tab
        # This works even when MPV has keyboard focus
        @self.player.on_key_press('ENTER')
        def handle_enter():
            self.root.after(0, self._mark_frame)
            return None  # Return None to prevent MPV from processing the key
        
        @self.player.on_key_press('KP_ENTER')
        def handle_kp_enter():
            self.root.after(0, self._mark_frame)
            return None
        
        @self.player.on_key_press('ESC')
        def handle_esc():
            self.root.after(0, self._mark_no_frame)
            return None  # Return None to prevent MPV from processing the key
        
        # Store reference to self for use in callbacks
        app_self = self
        
        # Unbind TAB and backtick in MPV to prevent warnings and console toggling
        try:
            self.player.command("keybind", "TAB", "ignore")
            self.player.command("keybind", "`", "ignore")  # Prevent console toggle
        except Exception:
            pass
        
        # Ctrl+Left/Right for video navigation - handle in MPV too
        @self.player.on_key_press('Ctrl+LEFT')
        def handle_ctrl_left_mpv():
            # Ctrl+Left: go to previous video
            if app_self.current_idx > 0:
                app_self.current_idx -= 1
                app_self.root.after(0, app_self._load_video)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Ctrl+RIGHT')
        def handle_ctrl_right_mpv():
            # Ctrl+Right: go to next video
            if app_self.current_idx < len(app_self.videos) - 1:
                app_self.current_idx += 1
                app_self.root.after(0, app_self._load_video)
            return None  # Prevent MPV from processing


        # Load video file
        self.player.play(str(self.current_video))
        self.player.pause = True  # Start paused

        # Wait for video to load
        import time
        time.sleep(0.2)  # Give MPV time to load video metadata
        self.root.update_idletasks()
        self.root.update()
        
        # Initialize current_frame using MPV's estimated-frame-number property
        try:
            # Try to get frame number directly from MPV
            for _ in range(20):  # Try up to 20 times
                try:
                    frame_num = self.player.get_property('estimated-frame-number')
                    if frame_num is not None:
                        self.current_frame = int(frame_num)
                        print(f"Initialized from estimated-frame-number: {self.current_frame}")
                        break
                except (AttributeError, TypeError):
                    pass
                time.sleep(0.05)
                self.root.update_idletasks()
            
            # Fallback: calculate from time-pos and fps, or use OSD
            if not hasattr(self, 'current_frame') or self.current_frame is None:
                # Try OSD first (most accurate)
                try:
                    osd_text = self.player.command('expand-text', '${estimated-frame-number}')
                    if osd_text:
                        self.current_frame = int(osd_text)
                        print(f"Initialized from OSD: {self.current_frame}")
                except (AttributeError, TypeError, ValueError, Exception):
                    # Fallback to time-pos calculation
                    fps = self._get_fps()
                    if fps is not None:
                        time_pos = self.player.time_pos or 0
                        self.current_frame = round(time_pos * fps)
                        print(f"Initialized from time_pos: time_pos={time_pos}, fps={fps}, frame={self.current_frame}")
                    else:
                        self.current_frame = 0
                        print(f"Could not initialize frame (no FPS available)")
        except Exception as e:
            self.current_frame = 0
            print(f"Error initializing frame: {e}")

        # Register property observer to update current_frame when estimated-frame-number changes
        # This is more accurate than time-pos for frame-accurate tracking
        try:
            @self.player.property_observer("estimated-frame-number")
            def frame_observer(_name, value):
                if value is not None:
                    try:
                        self.current_frame = int(value)
                        print(f"Frame updated from estimated-frame-number: {self.current_frame}")
                    except (ValueError, TypeError):
                        pass
        except Exception:
            # Fallback to time-pos observer if estimated-frame-number not available
            @self.player.property_observer("time-pos")
            def time_observer(_name, value):
                if value is not None and self.player:
                    try:
                        fps = self._get_fps()
                        if fps is not None:
                            new_frame = round(value * fps)
                            self.current_frame = new_frame
                            print(f"Frame updated from time_pos: time_pos={value}, fps={fps}, frame={new_frame}")
                    except (AttributeError, TypeError):
                        pass

        # Check if frame file already exists and seek to that frame
        trial_name = self.current_video.stem
        output_file = self.per_trial_dir / f"{trial_name}.txt"
        if output_file.exists():
            try:
                with open(output_file, "r") as f:
                    content = f.read().strip()
                    # Check if it's NaN
                    if content.lower() != "nan" and content:
                        frame_num = int(content)
                        # Seek to that frame
                        fps = self._get_fps()
                        if fps is not None:
                            time_pos = frame_num / fps
                            self.player.time_pos = time_pos
                            self.current_frame = frame_num
            except (ValueError, AttributeError, TypeError):
                # If reading fails, just start from beginning
                pass

        # Update display
        self._update_progress()

    def _mark_frame(self):
        """Mark current frame and advance to next video."""
        if not self.player:
            return

        # Get frame from OSD (most accurate - same as displayed)
        frame_from_osd = None
        try:
            osd_text = self.player.command('expand-text', '${estimated-frame-number}')
            if osd_text:
                frame_from_osd = int(osd_text)
        except (AttributeError, TypeError, ValueError, Exception) as e:
            print(f"Error getting frame from OSD/expand-text: {e}")

        # Get container FPS for diagnostic output
        container_fps = None
        try:
            fps_str = self.player.command('expand-text', '${container-fps}')
            if fps_str:
                container_fps = float(fps_str)
        except (AttributeError, TypeError, ValueError, Exception):
            pass

        # Determine which frame to save
        if self.fps_override is not None:
            # User provided --fps override: use time_pos * fps calculation
            time_pos = None
            frame_from_time = None
            try:
                time_pos = self.player.time_pos
                if time_pos is not None:
                    frame_from_time = round(time_pos * self.fps_override)
            except (AttributeError, TypeError, ValueError) as e:
                print(f"Error calculating frame from time_pos: {e}")
            
            frame = frame_from_time if frame_from_time is not None else 0
            
            # Diagnostic output
            print(f"Frame calculation (--fps {self.fps_override} override):")
            print(f"  time_pos: {time_pos}")
            print(f"  fps (override): {self.fps_override}")
            print(f"  container_fps: {container_fps}")
            print(f"  frame_from_time (round(time_pos * fps)): {frame_from_time}")
            print(f"  frame_from_osd (for comparison): {frame_from_osd}")
            print(f"  Saving frame: {frame}")
        else:
            # Default: use OSD frame number (most accurate)
            frame = frame_from_osd if frame_from_osd is not None else 0
            
            # Diagnostic output
            print(f"Frame from OSD: {frame_from_osd}")
            print(f"  container_fps: {container_fps}")
            print(f"  Saving frame: {frame}")
            
            if frame_from_osd is None:
                print(f"⚠️  WARNING: Could not get frame from OSD!")

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

    def _mark_no_frame(self):
        """Mark no frame selected (skip this video) and advance to next."""
        if not self.player:
            return

        # Save empty file or NaN to indicate no frame selected
        trial_name = self.current_video.stem
        output_file = self.per_trial_dir / f"{trial_name}.txt"
        with open(output_file, "w") as f:
            f.write("NaN")  # Use NaN to indicate no frame selected

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
                frame_str = f.read().strip()
                # Handle NaN or empty values
                if frame_str in ["NaN", "nan", "NAN", ""]:
                    frame = float('nan')
                else:
                    try:
                        frame = int(frame_str)
                    except ValueError:
                        frame = float('nan')

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
        help="Path to folder containing videos (e.g., resources/nextcloud/facial_expression) [deprecated: use --input-folder]",
    )
    parser.add_argument(
        "--input-folder",
        "--input",
        dest="input_folder_option",
        help="Path to folder containing videos (alternative to positional argument)",
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
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove output directory before starting (cannot be used with --continue)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Override frame calculation with time_pos * FPS instead of using MPV's OSD frame number. "
             "By default, frame numbers are taken directly from MPV's OSD display (most accurate). "
             "Use this flag only if you need to use a specific FPS for calculation.",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.clean and args.continue_session:
        print("Error: --clean cannot be used with --continue")
        sys.exit(1)

    # Handle clean option
    if args.clean:
        output_dir = Path(args.name)
        if output_dir.exists():
            import shutil
            print(f"Removing existing output directory: {output_dir}")
            shutil.rmtree(output_dir)
            print("Output directory removed.")

    # Handle continue session
    if args.continue_session:
        if not Path(args.continue_session).exists():
            print(f"Error: Output folder not found: {args.continue_session}")
            sys.exit(1)
        input_folder = None  # Will be loaded from config
    else:
        # Prefer --input-folder option over positional argument
        input_folder = args.input_folder_option or args.input_folder
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
            fps=args.fps,
        )
        reviewer.run()
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()

