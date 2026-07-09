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
| 0 | Per-coil resistance mismatch warning; widens Stage 2 lambda |
| 1 | Per-coil electrical time-constant mismatch warning; widens Stage 2 lambda |
| 2 | Reserved; tau residual is reported as telemetry, not a warning |
| 3 | Electrical delay/theta-to-tau ratio warning; widens Stage 2 lambda |
| 4 | Reserved/deprecated; successful current-validation retry is evidence, not an inner warning |
| 5 | Current gains fell back to defaults; forces conservative Stage 2 synthesis |
| 6 | Confidence fields are host defaults, not a fresh measurement; forces conservative Stage 2 synthesis |
| 7 | Reserved |

Non-zero displayable flags are shown in `FOCI_COMMISSION` and `FOCI_TUNE`
console output. Bits 0, 1, and 3 derate Stage 2 by widening lambda. Bits 5 and
6 force conservative Stage 2 synthesis when new gains are generated. Bit 4 is
kept reserved/deprecated because successful current-validation retry is reported
through current-loop evidence, not `inner_warning_flags`. Persisted outer gains
from an earlier tune remain unchanged until retuned.

## License

GPL-3.0. See `COPYING` at the repo root for the full text..
