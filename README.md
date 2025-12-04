# Video Frame Annotator

A simple GUI tool for manually annotating a specific frame per video. Uses MPV for smooth, frame-accurate video playback with hardware acceleration support.

## Features

- **Frame-accurate video playback** using MPV (hardware-accelerated)
- **Blind review mode** (default) - hides trial information to avoid bias
- **Randomized video order** - prevents order effects
- **Resume support** - continue interrupted sessions
- **Progress tracking** - see how many videos remain
- **Summary visualizations** - generate frame montages (grouped by source folder structure)

## Use Cases

This tool can be used for any task requiring frame-level annotation of videos. Common examples include:

- **Threat detection**: Mark the first frame where an animal shows a fear response
- **Behavior onset**: Identify when a specific behavior begins
- **Event marking**: Mark frames where specific events occur (e.g., stimulus presentation, response initiation)
- **Quality control**: Flag frames with artifacts or specific characteristics

## Installation

### Prerequisites

- Conda (recommended)
- The `environment.yml` uses **conda-forge** as the default channel

### Setup

1. Navigate to the video_frame_reviewer directory:
```bash
cd custom_scripts/video_frame_reviewer
```

2. (Optional) Set conda-forge as priority channel:
```bash
conda config --add channels conda-forge
conda config --set channel_priority strict
```

3. Create the conda environment:
```bash
conda env create -f environment.yml
conda activate video-reviewer
```

The environment file will:
- Install `mpv` (libmpv library) from conda-forge
- Install `python-mpv` (Python bindings) via pip (not available as conda package)
- Install other dependencies (opencv, matplotlib, numpy, pandas) from conda-forge

4. Verify MPV is installed:
```bash
mpv --version
```

### Platform-Specific Notes

**Linux/macOS**: The conda `mpv` package should work out of the box.

**Windows**: 
- The conda `mpv` package from conda-forge should provide `libmpv.dll`
- If you encounter issues, ensure `libmpv.dll` is in your PATH or next to `python.exe`
- According to the [python-mpv documentation](https://pypi.org/project/python-mpv/), Windows shared library handling can be tricky
- Alternative: Download MPV from [mpv.io](https://mpv.io/installation/) and ensure `libmpv.dll` is accessible

## Usage

### Basic Usage

Start a new scoring session:

```bash
python video_frame_reviewer.py /path/to/facial_expression --name "session1"
```

If no folder is provided, a file dialog will open:

```bash
python video_frame_reviewer.py --name "session1"
```

### Options

- `--name` (required): Name for the output folder
- `--description`: Description of the scoring session (saved in README.md)
- `--show-trial-info`: Show trial path information during review (default: blind mode)
- `--continue <folder>`: Continue from an existing output folder

### Examples

**New session with description (threat detection example):**
```bash
python video_frame_reviewer.py resources/nextcloud/facial_expression \
    --name "threat_onset_scoring" \
    --description "Scoring first frame where mouse shows fear response"
```

**Non-blind mode (show trial info):**
```bash
python video_frame_reviewer.py resources/nextcloud/facial_expression \
    --name "session1" \
    --show-trial-info
```

**Continue previous session:**
```bash
python video_frame_reviewer.py --continue session1
```

## Keyboard Controls

All controls work on both German and English keyboards:

| Key | Action |
|-----|--------|
| **Space** | Play/Pause |
| **Enter** | Mark current frame & advance to next video |
| **Left/Right** | Step one frame backward/forward |
| **Shift+Left/Right** | Seek backward/forward 5 seconds |
| **Up/Down** | Increase/Decrease playback speed (0.25x - 2.0x) |
| **Q** | Quit (progress is saved) |

## Output Structure

Each scoring session creates an output folder with the following structure:

```
<name>/
├── README.md           # Session description and metadata
├── config.json         # Configuration (input folder, blind mode, etc.)
├── per_trial/          # Individual frame annotations
│   ├── 2023-11-07-14-26-31.txt  # Frame number for this trial
│   ├── 2023-11-07-14-29-31.txt
│   └── ...
├── results.csv         # Merged results (trial, frame, relative_path, group, scorer, timestamp)
└── summary_plots/      # Frame montage visualizations (mirrors source folder structure)
    ├── 349/
    │   └── hab.png
    ├── 349_recall1.png
    └── ...
```

### File Formats

**Individual trial files** (`per_trial/*.txt`):
- Single line containing the frame number (0-indexed)

**Results CSV** (`results.csv`):
- Columns: `trial`, `frame`, `relative_path`, `group`, `scorer`, `timestamp`
- `group` mirrors the source folder structure (e.g., "349/hab" for videos in `<input>/349/hab/`)
- Sorted by trial name

## Workflow

1. **Start session**: Run the annotator with your video folder
2. **Review videos**: Watch each video, navigate frame-by-frame if needed
3. **Mark frames**: Press Enter when you identify the target frame
4. **Auto-advance**: Next video loads automatically
5. **Completion**: When done, optionally generate summary plots
6. **Results**: Check `results.csv` for all annotations

## Summary Plots

After completing a session, you can generate summary visualizations showing frames around the marked frame.

### Automatic Generation

The reviewer will ask if you want to generate plots when the session completes.

### Manual Generation

Generate plots separately:

```bash
python generate_summary_plots.py <output_folder> --video-folder <video_root>
```

Example:
```bash
python generate_summary_plots.py session1/ \
    --video-folder resources/nextcloud/facial_expression
```

### Plot Format

- **One plot per group** (mirrors source folder structure, e.g., `349/hab.png`)
- **One row per trial** (~20 rows)
- **7 columns**: 3 frames before marked frame, marked frame (red border), 3 frames after
- **Black background** for easy viewing

Options:
- `--frames-before N`: Show N frames before marked frame (default: 3)
- `--frames-after N`: Show N frames after marked frame (default: 3)

## Merging Annotations

If you need to manually merge annotations (e.g., after manual edits):

```bash
python merge_annotations.py <output_folder> [--video-folder <video_root>]
```

This regenerates `results.csv` from the individual `per_trial/*.txt` files.

## Tips

1. **Frame accuracy**: Use frame stepping (`,`/`.`) for precise frame selection
2. **Speed control**: Adjust playback speed (`-`/`+`) to quickly scan through videos
3. **Resume sessions**: Use `--continue` if you need to stop and resume later
4. **Blind mode**: Keep blind mode enabled to avoid bias from trial information
5. **Multiple sessions**: Use different `--name` values for different reviewers or conditions

## Troubleshooting

### MPV window doesn't appear

- Check that MPV is installed: `mpv --version`
- Try running MPV directly: `mpv <video_file>` to test
- On some systems, MPV may need X11 forwarding (Linux) or display server access

### Frame numbers seem incorrect

- Frame numbers are calculated from time position × FPS
- For frame-accurate marking, use frame stepping (`,`/`.`) rather than seeking
- Frame numbers are 0-indexed

### Videos not found

- Ensure the video folder path is correct
- Check that video files match the trial names in `per_trial/*.txt`
- Video extensions supported: `.avi`, `.mp4`, `.mov`, `.mkv`

### Keyboard shortcuts not working

- Make sure the Tkinter window has focus (click on it)
- Some window managers may intercept certain keys
- Try clicking the info window to ensure it has focus

## Dependencies

- Python >= 3.9
- mpv (libmpv library) - installed from conda-forge
- python-mpv (Python bindings) - installed via pip (not available as conda package)
- opencv, matplotlib, numpy, pandas - installed from conda-forge

All dependencies are listed in `environment.yml`. The environment uses **conda-forge** as the default channel, with `python-mpv` installed via pip within the conda environment.

