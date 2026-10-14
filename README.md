# GenBrowser

GenBrowser is a lightweight desktop image browser built with Python and PySide6 for **Linux and Windows**. It combines a thumbnail grid, a larger image preview, and an AI generation metadata panel. It's especially useful for sorting images created with **SwarmUI**, **ComfyUI**, and similar image gen applications, but it also works as a general-purpose image viewer.  No web server, image-generation backend, or database is required.



## Features

* **Three views:** a full-window thumbnail grid, a hybrid view with thumbnails/preview/metadata, and a distraction-free image viewer that fits the image to the window.
* **File-manager-style selection:** click to select; **Shift-click** for a continuous range; **Ctrl-click** to add or remove individual images. Works in grid and hybrid views.
* **Fast navigation:** use the mouse wheel or Left/Right arrows to move between images in the full-window viewer; **Ctrl+wheel** zooms.
* **Adjustable thumbnail size** using a toolbar slider. Thumbnails load using background workers.
* **Generation metadata:** readable fields for SwarmUI image parameters, extra data, and model details; support for embedded ComfyUI/other prompt metadata where available; a Raw/Parsed switch.
* **Image sorting:** right-click to move selected images to another folder, or use shortcuts to your three most recent destinations. Name collisions are not overwritten.
* **Trash support:** right-click or press **Delete** to send selected images to the operating system's Trash. Confirmation can be disabled in Settings.
* **Preferences:** optionally enlarge small images to fit the viewer. Preferences are stored per user.
* **Open images directly:** launch GenBrowser with a filename, including from a supported file manager association. It opens in full-window view and navigates other images in the same directory.

Supported extensions: PNG, JPEG, WebP, BMP, GIF, TIFF, and AVIF (when supported by the installed image codecs). Animated images are shown as still images.



## Install on Ubuntu / Linux

Prerequisites: Python 3.10 or newer, `venv`, pip, and a graphical desktop session. On Ubuntu 24.04:

```bash
sudo apt update
sudo apt install python3-venv python3-pip
```



Download and extract this repository into a **permanent location** such as `\~/Apps/genbrowser`, then run:

```bash
cd \~/Apps/genbrowser
./install\_ubuntu.sh
```



The script creates a local `.venv`, installs dependencies from `requirements.txt`, and adds a **GenBrowser** launcher to your user application menu. It does not require root privileges or remove other applications. The launcher uses the location you installed into; rerun the script if you move the directory.

Launch it via the application menu or manually:

```bash
./.venv/bin/python genbrowser.py
./.venv/bin/python genbrowser.py "/path/to/image.png"
```



To associate image files, right-click a PNG/JPEG/etc. in Ubuntu Files and choose **Properties → Open With → GenBrowser** (wording varies by desktop). A desktop logout/login may be needed before newly installed applications appear.

**Other Linux distributions:** install Python with `venv` and run `./install\_ubuntu.sh` if your desktop supports freedesktop `.desktop` launchers.



## Run on Windows

Install Python 3.10 or newer from [python.org](https://www.python.org/downloads/windows/) and ensure the Python Launcher (`py`) is installed. Extract the repository, then double-click **`start\_windows.bat`**. On first launch it creates `.venv` and installs dependencies; subsequent launches reuse it.

To open a specific image, pass its path to the launcher. The batch file does not automatically register Windows file associations; for a desktop shortcut or association, point to the batch file or configure a shortcut manually.



## Controls

|Action|Grid|Hybrid|Full-window viewer|
|-|-|-|-|
|Single click thumbnail|Select|Select and preview|N/A|
|Shift / Ctrl + click|Range / toggle selection|Range / toggle selection|N/A|
|Double-click thumbnail|Open hybrid|Open full-window|N/A|
|Click large preview|N/A|Open full-window|N/A|
|Escape|Stay in grid|Return to grid|Return to hybrid|
|Mouse wheel|Scroll thumbnails|Scroll thumbnails / navigate over preview|Previous / next image|
|Ctrl + mouse wheel|N/A|Zoom image over preview|Zoom image|
|Delete|Trash selection|Trash selection|Trash current image, show next|

Use **Open folder** or **Ctrl+O** to browse directories. The **Settings** dropdown offers **Confirm on Delete?** (on by default) and **Enlarge to fit?** (off by default). The image viewer fits large images to the available window; the second setting also enlarges smaller images.



## Notes and limitations

* GenBrowser scans one directory at a time. It does not recurse through subfolders.
* Thumbnail generation runs in background threads but is **not persisted to a disk cache**.
* Full-resolution image decoding happens in the GUI thread, so unusually large images may momentarily pause the interface.
* Embedded AI metadata varies by generator and output format. Files without relevant metadata still open normally.
* Some AI outputs, including SwarmUI-generated previews, may contain no embedded generation metadata.
* Windows installer/file-association integration is not included in this source release.
* 

## Project status

Early source release. The application has been exercised on Ubuntu, but no automated GUI test suite or signed installers are provided. Updates are unlikely unless I happen to think of some feature I can't live without.



### AI \& Safety Disclaimer

The code and documentation included in this project is primarily vibeslop. The human writing this sentence in particular can barely code and doesn't really understand how any of this works. It Works On My Machine and hasn't caused my genitals to explode, but your mileage may vary. I make absolutely no guarantee as to the safety or security of the contents of this project. Use at your own risk. Or don't.



## License

GenBrowser is released into the public domain under the [Unlicense](https://unlicense.org/).   

Copyleft 2026   

No Rights Reserved

