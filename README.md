# klipper-foci

Python Klipper extras module for FOCI servo controllers (TMC4671 + STM32 stepper drivers).

Part of the [FOCI](https://github.com/foci-rs/foci) project — a
Klipper/Kalico-compatible MCU firmware family for STM32 boards with
TMC4671 FOC servo controller ICs.

## Status

Pre-1.0; APIs may change without notice. Used in production firmware
on the OpenFFBoard test rig but not yet versioned for external
consumers.

## Use

Drop the package into your Klipper installation as a Klipper extras module:

```bash
scp -r foci/ pi@<host>:/home/pi/klipper/klippy/extras/foci/
```

See the [FOCI project README](https://github.com/foci-rs/foci) for full setup instructions.

## License

GPL-3.0. See `COPYING` at the repo root for the full text..
