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

## Motion Scale

FOCI reads `rotation_distance`, `full_steps_per_rotation`, and `microsteps`
directly from the linked Klipper stepper. It leaves all three mechanically
truthful settings untouched and sends the firmware only `encoder_ppr` and the
derived planner steps per revolution. Every common power-of-two microstep
selection from 1 through 256 is supported; 32 and 64 microsteps are normal
selections and do not need to match the encoder count.

For an LDO 1.8-degree stepper at 16 microsteps with a 1000 PPR encoder, startup
reports:

```text
planner=200*16=3200 steps/rev encoder=1000 ppr=4000 quadrature counts/rev
tmc_grid=4096 pulses/rev step_width=16 position_units/pulse pulse_ratio=4096/3200
accumulated_scale_error=0 instantaneous_error_bound=8 position_units
```

The startup diagnostic also shows the live configured `rotation_distance`.
Before enabling motion during rollout, remove any legacy hand compensation and
compare `rotation_distance` with the actual mechanical transmission. The host
cannot infer the truthful transmission distance from firmware scale data.

`FOCI_STEPPER_STATS` reports the firmware's authoritative logical and physical
directional counts, motion-scale values, and board admission/timing provenance.
The new protocol is intentionally incompatible: update host and firmware
together because the host does not provide an old-firmware fallback.

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
