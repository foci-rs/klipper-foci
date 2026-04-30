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

## Commissioning Diagnostics

`FOCI_COMMISSION` persists inner electrical identification fields for later
`FOCI_TUNE` runs. The host reports and persists `identified_inner_warning_flags`
as a bitfield:

| Bit | Meaning |
| --- | --- |
| 0 | Per-coil resistance mismatch warning |
| 1 | Per-coil electrical time-constant mismatch warning |
| 2 | Electrical tau cross-check residual warning |
| 3 | Electrical delay/theta-to-tau ratio warning |
| 4 | Current validation accepted after retry |
| 5 | Current gains fell back to defaults |
| 6 | Confidence fields are host defaults, not a fresh measurement |
| 7 | Reserved |

Non-zero flags are shown in `FOCI_COMMISSION` and `FOCI_TUNE` console output.
Bits 5 and 6 force conservative Stage 2 synthesis when new gains are generated;
persisted outer gains from an earlier tune remain unchanged until retuned.

## License

GPL-3.0. See `COPYING` at the repo root for the full text..
