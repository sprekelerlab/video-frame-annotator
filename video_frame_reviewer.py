#!/usr/bin/env python3
"""
Video Frame Annotator GUI

A tool for manually annotating a specific frame per video.
Uses MPV for smooth, frame-accurate video playback.
"""

import argparse
import json
import logging
import os
import random
import shutil
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Optional

from mpv_utils import MPVImportError, _format_mpv_import_error


try:
    import mpv
except Exception as exc:
    raise MPVImportError(_format_mpv_import_error(exc)) from exc


class VideoFrameReviewer:
    """Main application class for video frame reviewing."""

    def __init__(self, input_folder, output_name, description="", blind_mode=True, continue_session=None, fps=None, debug=False):
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
        self.debug = debug
        self.logger = logging.getLogger(__name__)

        # Font size configuration
        self.font_size_header = 12
        self.font_size_normal = 11
        self.font_size_small = 10

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
        all_videos = self._find_videos()
        if not all_videos:
            raise ValueError(f"No videos found in {self.input_folder}")

        # Handle video ordering: load stored order if continuing, otherwise shuffle and save
        if continue_session:
            # Load stored video order from config
            self.videos, order_updated = self._load_video_order(all_videos)
            if not self.videos:
                # Fallback: if order not found, shuffle and save
                self.videos = sorted(all_videos)
                random.shuffle(self.videos)
                self._save_video_order()
            elif order_updated:
                # New videos were added, save updated order
                self._save_video_order()
        else:
            # New session: shuffle and save order
            self.videos = sorted(all_videos)
            random.shuffle(self.videos)
            self._save_video_order()

        # Find first unmarked video index
        self.current_idx = self._find_first_unmarked_video()
        if self.current_idx is None:
            messagebox.showinfo("Complete", "All videos have already been scored!")
            sys.exit(0)
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
            self._go_to_previous_video()
            return "break"
        
        def handle_ctrl_right(event):
            # Ctrl+Right: go to next video
            self._go_to_next_video()
            return "break"
        
        def handle_ctrl_space(event):
            # Ctrl+Space: select video
            self._select_video()
            return "break"
        
        def handle_ctrl_q(event):
            # Ctrl+Q: quit application
            self._quit()
            return "break"
        
        def handle_ctrl_shift_space(event):
            # Ctrl+Shift+Space: go to next unmarked video
            self._go_to_next_unmarked_video()
            return "break"
        
        def handle_ctrl_p(event):
            # Ctrl+P: generate summary plots
            self._generate_summary_plots()
            return "break"
        
        self.root.bind_all("<Return>", handle_enter)
        self.root.bind_all("<KP_Enter>", handle_enter)
        self.root.bind_all("<Escape>", handle_esc)
        # Ctrl+Left/Right for video navigation
        self.root.bind_all("<Control-Left>", handle_ctrl_left)
        self.root.bind_all("<Control-Right>", handle_ctrl_right)
        # Ctrl+Shift+Space for next unmarked video navigation
        self.root.bind_all("<Control-Shift-space>", handle_ctrl_shift_space)
        # Ctrl+Space for video selection
        self.root.bind_all("<Control-space>", handle_ctrl_space)
        # Ctrl+P to generate plots
        self.root.bind_all("<Control-p>", handle_ctrl_p)
        self.root.bind_all("<Control-P>", handle_ctrl_p)
        # Ctrl+Q to quit
        self.root.bind_all("<Control-q>", handle_ctrl_q)
        self.root.bind_all("<Control-Q>", handle_ctrl_q)
        
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

    def _find_first_unmarked_video(self):
        """
        Find the index of the first video that hasn't been scored yet.
        
        Returns
        -------
        int or None
            Index of first unmarked video, or None if all are marked.
        """
        scored_trials = set()
        if self.per_trial_dir.exists():
            for txt_file in self.per_trial_dir.glob("*.txt"):
                scored_trials.add(txt_file.stem)

        # Find first unmarked video
        for idx, video in enumerate(self.videos):
            trial_name = video.stem
            if trial_name not in scored_trials:
                return idx

        return None  # All videos are marked

    def _save_video_order(self):
        """Save the current video order to config.json."""
        config_path = self.output_dir / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
        else:
            config = {}

        # Store video paths as strings (relative to input_folder if possible, else absolute)
        video_paths = []
        for video in self.videos:
            if self.input_folder and self.input_folder in video.parents:
                try:
                    video_paths.append(str(video.relative_to(self.input_folder)))
                except ValueError:
                    video_paths.append(str(video))
            else:
                video_paths.append(str(video))

        config["video_order"] = video_paths
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

    def _load_video_order(self, all_videos):
        """
        Load stored video order from config.json and match with current videos.
        
        Parameters
        ----------
        all_videos : list
            List of all video Path objects found in input folder.
        
        Returns
        -------
        tuple
            (ordered_videos, was_updated) where ordered_videos is list of video Path objects
            in stored order (or empty if not found), and was_updated is True if new videos
            were added to the stored order.
        """
        config_path = self.output_dir / "config.json"
        if not config_path.exists():
            return ([], False)

        with open(config_path, "r") as f:
            config = json.load(f)

        video_order = config.get("video_order")
        if not video_order:
            return ([], False)

        # Create lookup: video path (as string) -> video Path object
        video_lookup = {}
        for video in all_videos:
            # Try relative path first
            if self.input_folder and self.input_folder in video.parents:
                try:
                    rel_path = str(video.relative_to(self.input_folder))
                    video_lookup[rel_path] = video
                except ValueError:
                    pass
            # Also try absolute path
            video_lookup[str(video)] = video

        # Reconstruct order
        ordered_videos = []
        for stored_path in video_order:
            if stored_path in video_lookup:
                ordered_videos.append(video_lookup[stored_path])
            else:
                # Video not found - might have been deleted, skip it
                self.logger.warning(f"Video from stored order not found: {stored_path}")

        # Add any new videos that weren't in the stored order (append at end)
        existing_stems = {v.stem for v in ordered_videos}
        new_videos_added = False
        for video in all_videos:
            if video.stem not in existing_stems:
                ordered_videos.append(video)
                new_videos_added = True

        return (ordered_videos, new_videos_added)

    def _save_config(self):
        """Save configuration to config.json."""
        config = {
            "input_folder": str(self.input_folder) if self.input_folder else None,
            "blind_mode": self.blind_mode,
            "description": self.description,
        }
        # Note: video_order is saved separately via _save_video_order()
        # to ensure it's saved after videos are shuffled
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

        # Left side: instructions with centered header
        left_frame = tk.Frame(top_frame, bg="black")
        left_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Keyboard Shortcuts header (centered, bold)
        shortcuts_header = tk.Label(
            left_frame,
            text="Keyboard Shortcuts",
            bg="black",
            fg="white",
            font=("TkDefaultFont", self.font_size_header, "bold"),
        )
        shortcuts_header.pack(pady=(0, 2))

        # Instructions text widget with colored keys (3 lines, centered)
        self.instructions_text = tk.Text(
            left_frame,
            bg="black",
            fg="lightgray",
            wrap=tk.NONE,  # No wrapping, we control line breaks
            height=3,
            width=120,  # Increased width to prevent text cutoff
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            font=("TkDefaultFont", self.font_size_normal),
            padx=10,
            pady=2,
        )
        self.instructions_text.pack(padx=10)
        
        # Define color tags for different key groups (using matplotlib dark_background colors)
        # Create bold font for key names
        bold_font = ("TkDefaultFont", 11, "bold")
        
        self.instructions_text.tag_config("mark", foreground="#b3de69", font=bold_font)  # Light green for marking
        self.instructions_text.tag_config("skip", foreground="#fa8174", font=bold_font)  # Coral/reddish-orange for skip
        self.instructions_text.tag_config("playback", foreground="#81b1d2", font=bold_font)  # Light blue for playback
        self.instructions_text.tag_config("speed", foreground="#bfbbd9", font=bold_font)  # Lavender/purple for speed
        self.instructions_text.tag_config("seek75", foreground="#8dd3c7", font=bold_font)  # Teal/cyan for 75 frame jumps
        self.instructions_text.tag_config("seek15", foreground="#ccebc4", font=bold_font)  # Mint green for 15 frame jumps
        self.instructions_text.tag_config("frame", foreground="#feffb3", font=bold_font)  # Light yellow for single frame
        self.instructions_text.tag_config("adjust", foreground="#bc82bd", font=bold_font)  # Purple/magenta for contrast/brightness
        self.instructions_text.tag_config("separator", foreground="#ffffff")  # White for separators
        
        # Build instructions with colored text - Line 1: Enter until Speed
        self.instructions_text.insert("1.0", "Enter", "mark")
        self.instructions_text.insert(tk.END, ": Mark selected frame | ", "separator")
        self.instructions_text.insert(tk.END, "ESC", "skip")
        self.instructions_text.insert(tk.END, ": Mark no frame | ", "separator")
        self.instructions_text.insert(tk.END, "Space", "playback")
        self.instructions_text.insert(tk.END, ": Play/Pause | ", "separator")
        self.instructions_text.insert(tk.END, "[ ]", "speed")
        self.instructions_text.insert(tk.END, ": Speed", "separator")
        self.instructions_text.insert(tk.END, "\n", "separator")
        
        # Line 2: All jump frames
        self.instructions_text.insert(tk.END, "Left/Right", "seek75")
        self.instructions_text.insert(tk.END, ": Jump 75 frames | ", "separator")
        self.instructions_text.insert(tk.END, "Shift+Left/Right", "seek15")
        self.instructions_text.insert(tk.END, ": Jump 15 frames | ", "separator")
        self.instructions_text.insert(tk.END, ", .", "frame")
        self.instructions_text.insert(tk.END, ": Jump 1 frame", "separator")
        self.instructions_text.insert(tk.END, "\n", "separator")
        
        # Line 3: Contrast and brightness
        self.instructions_text.insert(tk.END, "1 2", "adjust")
        self.instructions_text.insert(tk.END, ": Contrast | ", "separator")
        self.instructions_text.insert(tk.END, "3 4", "adjust")
        self.instructions_text.insert(tk.END, ": Brightness", "separator")
        
        # Center all text lines
        self.instructions_text.tag_add("center", "1.0", "end")
        self.instructions_text.tag_config("center", justify=tk.CENTER)
        self.instructions_text.config(state=tk.DISABLED)  # Make read-only

        # Video info label (only if not blind mode)
        self.video_info_label = tk.Label(
            left_frame,
            text="",
            bg="black",
            fg="gray",
            font=("TkDefaultFont", self.font_size_normal),
        )
        if not self.blind_mode:
            self.video_info_label.pack(pady=2)

        # Right side: navigation buttons, progress label, and quit
        right_frame = tk.Frame(top_frame, bg="black")
        right_frame.pack(side=tk.RIGHT, padx=10)

        # Note about progress being saved
        note_label = tk.Label(
            right_frame,
            text="Progress is saved automatically",
            bg="black",
            fg="lightgray",
            font=("TkDefaultFont", self.font_size_small),
        )
        note_label.pack(side=tk.TOP, pady=(0, 5))

        # Container frame for progress labels and buttons (horizontal layout)
        content_frame = tk.Frame(right_frame, bg="black")
        content_frame.pack(side=tk.TOP)

        # Progress labels frame (left side)
        progress_frame = tk.Frame(content_frame, bg="black")
        progress_frame.pack(side=tk.LEFT, padx=10)

        # Video counter label (first line)
        self.video_label = tk.Label(
            progress_frame,
            text="",
            bg="black",
            fg="white",
            font=("TkDefaultFont", self.font_size_normal),
        )
        self.video_label.pack()

        # Marking status label (second line)
        self.marking_status_label = tk.Label(
            progress_frame,
            text="",
            bg="black",
            fg="white",
            font=("TkDefaultFont", self.font_size_normal),
        )
        self.marking_status_label.pack()

        # Marked counter label (third line)
        self.marked_label = tk.Label(
            progress_frame,
            text="",
            bg="black",
            fg="white",
            font=("TkDefaultFont", self.font_size_normal),
        )
        self.marked_label.pack()

        # Button frame for navigation and quit buttons (right side)
        button_frame = tk.Frame(content_frame, bg="black")
        button_frame.pack(side=tk.LEFT)

        # Previous button
        self.prev_button = tk.Button(
            button_frame,
            text="Previous video\n(Ctrl+Left)",
            command=self._go_to_previous_video,
            bg="gray",
            fg="white",
            font=("TkDefaultFont", self.font_size_normal),
            width=16,
            relief=tk.RAISED,
            bd=2,
        )
        self.prev_button.pack(side=tk.LEFT, padx=2)

        # Next button
        self.next_button = tk.Button(
            button_frame,
            text="Next video\n(Ctrl+Right)",
            command=self._go_to_next_video,
            bg="gray",
            fg="white",
            font=("TkDefaultFont", self.font_size_normal),
            width=16,
            relief=tk.RAISED,
            bd=2,
        )
        self.next_button.pack(side=tk.LEFT, padx=2)

        # Select video button
        self.select_button = tk.Button(
            button_frame,
            text="Select video\n(Ctrl+Space)",
            command=self._select_video,
            bg="gray",
            fg="white",
            font=("TkDefaultFont", self.font_size_normal),
            width=16,
            relief=tk.RAISED,
            bd=2,
        )
        self.select_button.pack(side=tk.LEFT, padx=2)

        # Next unmarked button
        self.next_unmarked_button = tk.Button(
            button_frame,
            text="Next unmarked\n(Ctrl+Shift+Space)",
            command=self._go_to_next_unmarked_video,
            bg="gray",
            fg="white",
            font=("TkDefaultFont", self.font_size_normal),
            width=20,
            relief=tk.RAISED,
            bd=2,
        )
        self.next_unmarked_button.pack(side=tk.LEFT, padx=2)

        # Generate plots button
        self.generate_plots_button = tk.Button(
            button_frame,
            text="Generate plots\n(Ctrl+P)",
            command=self._generate_summary_plots,
            bg="#81b1d2",  # Light blue from matplotlib dark_background
            fg="black",
            font=("TkDefaultFont", self.font_size_normal),
            width=16,
            relief=tk.RAISED,
            bd=2,
        )
        self.generate_plots_button.pack(side=tk.LEFT, padx=2)

        # Quit button
        self.quit_button = tk.Button(
            button_frame,
            text="Quit\n(Ctrl+Q)",
            command=self._quit,
            bg="#fa8174",  # Coral/reddish-orange from matplotlib dark_background
            fg="black",
            font=("TkDefaultFont", self.font_size_normal),
            width=10,
            relief=tk.RAISED,
            bd=2,
        )
        self.quit_button.pack(side=tk.LEFT, padx=2)

        # Video container frame for MPV embedding
        self.video_frame = tk.Frame(self.root, bg="black", highlightthickness=0)
        self.video_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Update progress display
        self._update_progress()


    def _get_current_marking_status(self):
        """
        Get the marking status for the current video.
        
        Returns
        -------
        str
            "Marked frame: <number|None>" if marked, "Not marked" if unmarked.
        """
        if self.current_idx >= len(self.videos):
            return "Not marked"
        
        trial_name = self.videos[self.current_idx].stem
        output_file = self.per_trial_dir / f"{trial_name}.txt"
        
        if not output_file.exists():
            return "Not marked"
        
        try:
            with open(output_file, "r") as f:
                content = f.read().strip()
                # Check if it's NaN
                if content.lower() in ["nan", ""] or not content:
                    return "Marked frame: None"
                else:
                    frame_num = int(content)
                    return f"Marked frame: {frame_num}"
        except (ValueError, IOError):
            return "Not marked"

    def _update_progress(self):
        """Update progress display."""
        total = len(self.videos)
        current = self.current_idx + 1
        
        # Count how many videos have been marked
        scored_count = 0
        if self.per_trial_dir.exists():
            scored_count = len(list(self.per_trial_dir.glob("*.txt")))
        
        # Update video and marked labels separately
        if hasattr(self, 'video_label'):
            self.video_label.config(text=f"Video {current}/{total}")
        
        # Update marking status label
        if hasattr(self, 'marking_status_label'):
            marking_status = self._get_current_marking_status()
            self.marking_status_label.config(text=marking_status)
        
        if hasattr(self, 'marked_label'):
            self.marked_label.config(text=f"Videos marked: {scored_count}/{total}")
        
        # Update button states
        if hasattr(self, 'prev_button'):
            self.prev_button.config(state=tk.NORMAL if self.current_idx > 0 else tk.DISABLED)
        if hasattr(self, 'next_button'):
            self.next_button.config(state=tk.NORMAL if self.current_idx < len(self.videos) - 1 else tk.DISABLED)

    def _go_to_previous_video(self):
        """Navigate to previous video."""
        if self.current_idx > 0:
            self.current_idx -= 1
            trial_name = self.videos[self.current_idx].stem
            self.logger.debug(f"Navigated to video {trial_name}")
            self._load_video()

    def _go_to_next_video(self):
        """Navigate to next video."""
        if self.current_idx < len(self.videos) - 1:
            self.current_idx += 1
            trial_name = self.videos[self.current_idx].stem
            self.logger.debug(f"Navigated to video {trial_name}")
            self._load_video()

    def _go_to_next_unmarked_video(self):
        """Navigate to next unmarked video."""
        scored_trials = set()
        if self.per_trial_dir.exists():
            for txt_file in self.per_trial_dir.glob("*.txt"):
                # Check if file contains valid frame number (not just "NaN")
                try:
                    with open(txt_file, "r") as f:
                        content = f.read().strip()
                        if content and content.lower() != "nan":
                            scored_trials.add(txt_file.stem)
                except Exception:
                    pass

        # Search forwards from current position
        for idx in range(self.current_idx + 1, len(self.videos)):
            trial_name = self.videos[idx].stem
            if trial_name not in scored_trials:
                self.current_idx = idx
                self.logger.debug(f"Navigated to unmarked video {trial_name}")
                self._load_video()
                return

        # If no unmarked video found after current, wrap around and search from beginning
        for idx in range(0, self.current_idx):
            trial_name = self.videos[idx].stem
            if trial_name not in scored_trials:
                self.current_idx = idx
                self.logger.debug(f"Navigated to unmarked video {trial_name}")
                self._load_video()
                return

    def _select_video(self):
        """Show dialog to select video by ID and navigate to it."""
        # Use after() to ensure dialog is shown after any pending events
        self.root.after(10, self._show_select_video_dialog)
    
    def _show_select_video_dialog(self):
        """Show the video selection dialog."""
        try:
            # Ensure root window has focus before showing dialog
            self.root.focus_set()
            self.root.update_idletasks()
            
            total = len(self.videos)
            if total == 0:
                messagebox.showwarning("No Videos", "No videos available.")
                return
            
            current = self.current_idx + 1  # 1-based for display
            
            # Show input dialog
            video_id = simpledialog.askinteger(
                "Select Video",
                f"Enter video number (1-{total}):\nCurrent: {current}/{total}",
                parent=self.root,
                minvalue=1,
                maxvalue=total,
            )
            
            if video_id is not None:
                # Convert from 1-based (user input) to 0-based (internal index)
                new_idx = video_id - 1
                if 0 <= new_idx < len(self.videos):
                    self.current_idx = new_idx
                    trial_name = self.videos[self.current_idx].stem
                    self.logger.debug(f"Navigated to video {video_id}: {trial_name}")
                    self._load_video()
                else:
                    messagebox.showerror("Error", f"Invalid video number: {video_id}")
        except Exception as e:
            self.logger.error(f"Error in _select_video: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to select video: {e}")

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
        # Also unbind Q and Ctrl+Q to prevent MPV from quitting
        try:
            self.player.command("keybind", "TAB", "ignore")
            self.player.command("keybind", "`", "ignore")  # Prevent console toggle
            self.player.command("keybind", "q", "ignore")  # Prevent MPV from quitting on Q
            self.player.command("keybind", "Ctrl+q", "ignore")  # Prevent MPV from handling Ctrl+Q
            self.player.command("keybind", "Ctrl+Q", "ignore")  # Prevent MPV from handling Ctrl+Q (uppercase)
        except Exception:
            pass
        
        # Ctrl+Left/Right for video navigation - handle in MPV too
        @self.player.on_key_press('Ctrl+LEFT')
        def handle_ctrl_left_mpv():
            # Ctrl+Left: go to previous video
            app_self.root.after(0, app_self._go_to_previous_video)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Ctrl+RIGHT')
        def handle_ctrl_right_mpv():
            # Ctrl+Right: go to next video
            app_self.root.after(0, app_self._go_to_next_video)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Ctrl+SPACE')
        def handle_ctrl_space_mpv():
            # Ctrl+Space: select video
            app_self.root.after(0, app_self._select_video)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Ctrl+Shift+SPACE')
        def handle_ctrl_shift_space_mpv():
            # Ctrl+Shift+Space: go to next unmarked video
            app_self.root.after(0, app_self._go_to_next_unmarked_video)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Ctrl+P')
        def handle_ctrl_p_mpv_upper():
            # Ctrl+P: generate summary plots
            app_self.root.after(0, app_self._generate_summary_plots)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Ctrl+p')
        def handle_ctrl_p_mpv_lower():
            # Ctrl+p: generate summary plots
            app_self.root.after(0, app_self._generate_summary_plots)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Q')
        def handle_q_mpv():
            # Q: prevent MPV from quitting, do nothing (use Ctrl+Q to quit app)
            return None  # Prevent MPV from processing
        
        # Try both uppercase and lowercase Q for Ctrl+Q
        @self.player.on_key_press('Ctrl+Q')
        def handle_ctrl_q_mpv_upper():
            # Ctrl+Q: quit application
            app_self.root.after(0, app_self._quit)
            return None  # Prevent MPV from processing
        
        @self.player.on_key_press('Ctrl+q')
        def handle_ctrl_q_mpv_lower():
            # Ctrl+q: quit application
            app_self.root.after(0, app_self._quit)
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
            self.logger.debug(f"Frame from OSD: {frame_from_osd}")
            self.logger.debug(f"  container_fps: {container_fps}")
            self.logger.debug(f"  Saving frame: {frame}")
            
            if frame_from_osd is None:
                self.logger.warning(f"Could not get frame from OSD!")

        # Save frame number to file
        trial_name = self.current_video.stem
        output_file = self.per_trial_dir / f"{trial_name}.txt"
        with open(output_file, "w") as f:
            f.write(str(frame))
        
        # Log frame update
        self.logger.info(f"Updating {trial_name} with frame {frame}")

        # Advance to next video
        self.current_idx += 1
        if self.current_idx < len(self.videos):
            self._load_video()
        else:
            # Stay at last video (don't advance past it) and show completion dialog
            self.current_idx = len(self.videos) - 1
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

        # Log frame update
        self.logger.info(f"Updating {trial_name} with frame NaN")

        # Advance to next video
        self.current_idx += 1
        if self.current_idx < len(self.videos):
            self._load_video()
        else:
            # Stay at last video (don't advance past it) and show completion dialog
            self.current_idx = len(self.videos) - 1
            self._finish_session()

    def _finish_session(self):
        """Handle session completion."""
        # Don't terminate MPV - keep it running so user can continue reviewing
        # MPV will stay at the last video

        # Merge annotations
        self._merge_annotations()

        # Update progress display first
        self._update_progress()
        
        # Give GUI a moment to update the display before showing dialog
        self.root.update_idletasks()
        self.root.update()
        import time
        time.sleep(0.3)  # Small delay to ensure progress display updates

        # Ask about next steps
        response = self._show_session_complete_dialog()

        if response == "generate_plots":
            # Don't show messagebox here - _generate_summary_plots() will show its own
            # This avoids potential X11 conflicts with MPV window
            self._generate_summary_plots()
            # Don't quit immediately - let plot generation finish in background
            # User can close the window manually or it will close after plots are done
        elif response == "continue":
            # Already at last video, MPV is still running - just continue reviewing
            # No need to reload video, it's already there
            pass
        elif response == "quit":
            messagebox.showinfo("Complete", "Session complete! Results saved.")
            self.root.quit()

    def _show_session_complete_dialog(self):
        """
        Show custom dialog when session is complete.
        
        Returns
        -------
        str
            One of: "continue", "generate_plots", "quit", or None if dialog closed
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("Session Complete")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        result = {"value": None}
        
        # Message label
        message = (
            f"All {len(self.videos)} videos have been scored!\n\n"
            "Would you like to continue to revisit markings, generate summary plots "
            "(can take a few minutes) or quit?"
        )
        label = tk.Label(
            dialog,
            text=message,
            padx=20,
            pady=20,
            justify=tk.LEFT,
            wraplength=400,
            font=("TkDefaultFont", self.font_size_normal),
        )
        label.pack()
        
        # Button frame
        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=10, padx=20)
        
        def set_result(value):
            result["value"] = value
            dialog.destroy()
        
        # Buttons
        btn_continue = tk.Button(
            button_frame,
            text="Continue",
            command=lambda: set_result("continue"),
            width=15,
            font=("TkDefaultFont", self.font_size_normal),
        )
        btn_continue.pack(side=tk.LEFT, padx=5)
        
        btn_generate = tk.Button(
            button_frame,
            text="Generate summary plots",
            command=lambda: set_result("generate_plots"),
            width=20,
            font=("TkDefaultFont", self.font_size_normal),
        )
        btn_generate.pack(side=tk.LEFT, padx=5)
        
        btn_quit = tk.Button(
            button_frame,
            text="Quit without plotting",
            command=lambda: set_result("quit"),
            width=18,
            font=("TkDefaultFont", self.font_size_normal),
        )
        btn_quit.pack(side=tk.LEFT, padx=5)
        
        # Handle window close
        dialog.protocol("WM_DELETE_WINDOW", lambda: set_result("quit"))
        
        # Wait for dialog to close
        dialog.wait_window()
        
        return result["value"]

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

        self.logger.debug("=== PLOT GENERATION START ===")
        
        # Merge annotations first to ensure results.csv is up to date
        self._merge_annotations()
        
        if not self.input_folder or not self.input_folder.exists():
            self.logger.error(f"Input folder not found: {self.input_folder}")
            messagebox.showerror(
                "Error",
                "Cannot generate summary plots: video folder not found. "
                "Please run generate_summary_plots.py manually with --video-folder argument.",
            )
            return

        script_path = Path(__file__).parent / "generate_summary_plots.py"
        if not script_path.exists():
            self.logger.error(f"Script not found: {script_path}")
            messagebox.showwarning(
                "Warning",
                "generate_summary_plots.py not found. Please run it manually.",
            )
            return

        self.logger.debug(f"Script path: {script_path}")
        self.logger.debug(f"Output dir: {self.output_dir}")
        self.logger.debug(f"Video folder: {self.input_folder}")
        
        # Create a modal "Generating..." dialog that stays visible while script runs
        dialog = tk.Toplevel(self.root)
        dialog.title("Generating Plots")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Message label
        label = tk.Label(
            dialog,
            text="Generating summary plots...\n\nPlease check terminal for progress.",
            padx=20,
            pady=20,
            justify=tk.LEFT,
            font=("TkDefaultFont", self.font_size_normal),
        )
        label.pack()
        
        # Update GUI to show the dialog
        dialog.update()
        self.logger.debug("Generating dialog shown")
        
        print("\n*** GENERATING SUMMARY PLOTS ***")
        print("Please wait... Check progress bar below.\n")
        self.logger.info("Starting plot generation subprocess")
        
        # Run subprocess (blocking) - dialog stays visible
        try:
            cmd = [
                sys.executable,
                str(script_path),
                str(self.output_dir),
                "--video-folder",
                str(self.input_folder),
            ]
            self.logger.debug(f"Running: {' '.join(cmd)}")
            
            # Set environment variable to indicate we're running from GUI
            env = os.environ.copy()
            env["VIDEO_FRAME_REVIEWER_GUI"] = "1"
            
            result = subprocess.run(cmd, check=True, env=env)
            
            # Close generating dialog
            self.logger.debug("Closing generating dialog")
            dialog.destroy()
            
            self.logger.debug(f"Subprocess completed with return code: {result.returncode}")
            self.logger.debug("Showing success dialog...")
            # Show success dialog with Close button
            success_dialog = tk.Toplevel(self.root)
            success_dialog.title("Plots Generated")
            success_dialog.transient(self.root)
            success_dialog.grab_set()
            success_dialog.resizable(False, False)
            
            # Center the dialog
            success_dialog.update_idletasks()
            x = (success_dialog.winfo_screenwidth() // 2) - (success_dialog.winfo_width() // 2)
            y = (success_dialog.winfo_screenheight() // 2) - (success_dialog.winfo_height() // 2)
            success_dialog.geometry(f"+{x}+{y}")
            
            result_choice = {"value": None}
            
            # Success message
            success_label = tk.Label(
                success_dialog,
                text="Plots generated successfully!",
                padx=20,
                pady=20,
                font=("TkDefaultFont", self.font_size_normal),
            )
            success_label.pack()
            
            # Button frame
            button_frame = tk.Frame(success_dialog)
            button_frame.pack(pady=10)
            
            def set_choice(value):
                result_choice["value"] = value
                success_dialog.destroy()
            
            # Continue button
            continue_button = tk.Button(
                button_frame,
                text="Continue Reviewing",
                command=lambda: set_choice("continue"),
                width=18,
                font=("TkDefaultFont", self.font_size_normal),
            )
            continue_button.pack(side=tk.LEFT, padx=5)
            
            # Quit button
            quit_button = tk.Button(
                button_frame,
                text="Quit",
                command=lambda: set_choice("quit"),
                width=10,
                font=("TkDefaultFont", self.font_size_normal),
            )
            quit_button.pack(side=tk.LEFT, padx=5)
            
            # Wait for user choice
            success_dialog.wait_window()
            
            self.logger.debug(f"User choice: {result_choice['value']}")
            
            if result_choice["value"] == "quit":
                self.logger.debug("Quitting application")
                self._quit()
            # If "continue", just return and keep reviewing
            
            self.logger.debug("=== PLOT GENERATION END ===")
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Subprocess failed with return code {e.returncode}")
            
            # Close generating dialog
            try:
                dialog.destroy()
            except:
                pass
            
            # Show error dialog
            error_msg = (
                f"Failed to generate summary plots (return code: {e.returncode}).\n\n"
                "Check terminal for detailed error messages."
            )
            messagebox.showerror("Error", error_msg)
            self.logger.debug("=== PLOT GENERATION END (ERROR) ===")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}", exc_info=True)
            
            # Close generating dialog
            try:
                dialog.destroy()
            except:
                pass
            
            # Show error dialog
            error_msg = f"Unexpected error while generating plots: {e}"
            messagebox.showerror("Error", error_msg)
            self.logger.debug("=== PLOT GENERATION END (ERROR) ===")

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
        description="Video Frame Annotator - Manual annotation tool for marking specific frames in videos"
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
        "--yes",
        action="store_true",
        help="Skip confirmation prompt when using --clean",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Override frame calculation with time_pos * FPS instead of using MPV's OSD frame number. "
             "By default, frame numbers are taken directly from MPV's OSD display (most accurate). "
             "Use this flag only if you need to use a specific FPS for calculation.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG level logging",
    )

    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(levelname)s: %(message)s'
    )

    # Validate arguments
    if args.clean and args.continue_session:
        print("Error: --clean cannot be used with --continue")
        sys.exit(1)

    # Handle clean option
    if args.clean:
        output_dir = Path(args.name)
        if output_dir.exists():
            # Ask for confirmation unless --yes is provided
            if not args.yes:
                response = input(f"Are you sure you want to delete '{output_dir}'? This cannot be undone. [y/N]: ")
                if response.lower() not in ['y', 'yes']:
                    print("Clean operation cancelled.")
                    sys.exit(0)
            
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
            debug=args.debug,
        )
        reviewer.run()
    except Exception as e:
        messagebox.showerror("Error", f"An error occurred: {e}")
        raise


if __name__ == "__main__":
    main()

