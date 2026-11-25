# Running without Docker

← [Back to the README](../README.md) · [Docker hosting](docker.md)

**Windows:** Install Python 3.10 or later and double-click [`run.bat`](../run.bat). It creates a virtual environment, installs dependencies, and opens [http://127.0.0.1:8000](http://127.0.0.1:8000). Use `run.bat --port 8080` if port 8000 is in use.

**macOS or Linux:** From a checkout of this repository, run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app
```

The local launcher listens on your own machine only. Use [Docker hosting](docker.md) for shared access and PDF indexing.

For a local installation, set `DND_TRACKER_PDF_ROOT` to an absolute folder path before launching the app to enable the picker. [Docker hosting](docker.md) configures it automatically. Other settings are listed in the [configuration reference](configuration.md). Files are not uploaded or copied: picker links are relative to the library folder, so you can move the library without relinking if you keep its folder structure.
