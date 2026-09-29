# klipper-foci

Python Klipper extras module for FOCI servo controllers (TMC4671 + STM32 stepper drivers).

Part of the [FOCI](https://github.com/foci-rs/foci) project, a
Klipper/Kalico-compatible MCU firmware family for STM32 boards with
TMC4671 FOC servo controller ICs.

## Status

Pre-1.0; APIs may change without notice. Used in production firmware
on the OpenFFBoard test rig but not yet versioned for external
consumers.

## Deployment

The recommended install is a single command, run on the printer:

```sh
curl -sL https://raw.githubusercontent.com/foci-rs/foci/main/install.sh | bash
```

Add `-s -- --diagnostics` before the pipe's final `bash` to also install
the optional diagnostics package, for example:

```sh
curl -sL https://raw.githubusercontent.com/foci-rs/foci/main/install.sh | bash -s -- --diagnostics
```

(`bash -s -- <args>` is required, not `bash -- <args>`: a script fed on
stdin has no filename argument of its own, so a bare `--` after `bash` is
parsed as the script's positional filename rather than an argument
separator.) This detects Kalico vs. mainline Klipper, installs from this
project's self-hosted package index, places the loader shim in the right
directory, and registers the package with Moonraker's `update_manager` so
the printer can self-update going forward.

### Manual install (development / troubleshooting)

1. Install the packages you need into Klipper's virtual environment
   (`klippy-env`):

   ```sh
   ~/klippy-env/bin/pip install --index-url https://foci-rs.github.io/klipper-foci/simple/ klipper-foci
   # optionally:
   ~/klippy-env/bin/pip install --index-url https://foci-rs.github.io/klipper-foci/simple/ klipper-foci-diagnostics
   ```

2. Copy the shim to the right directory for your distribution. All the
   actual logic stays in the pip-installed package either way:

   - **Mainline Klipper**: copy `deploy/klippy-extras/foci.py` to
     `<klipper>/klippy/extras/foci.py`. Mainline Klipper's loader only
     scans `klippy/extras/`.
   - **Kalico**: copy `deploy/klippy-plugins/foci.py` to
     `<klipper>/klippy/plugins/foci.py`. Kalico's loader scans both
     `klippy/extras/` and `klippy/plugins/`, but `klippy/plugins/` keeps
     the shim out of the directory Kalico's own extras modules live in.

See the [FOCI documentation](https://foci.rs/getting-started/installation/) for full setup instructions.

## License

GPL-3.0. See `LICENSE` at the repo root for the full text.
