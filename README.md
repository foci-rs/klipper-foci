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
directional counts, motion-scale values, and waveform/runtime-lateness fields.
The new protocol is intentionally incompatible: update host and firmware
together because the host does not provide an old-firmware fallback.

## Commissioning Diagnostics

`FOCI_SETUP` persists inner electrical identification fields for later
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

Non-zero displayable flags are shown in `FOCI_SETUP` and `FOCI_TUNE`
console output. Bits 0, 1, and 3 derate Stage 2 by widening lambda. Bits 5 and
6 force conservative Stage 2 synthesis when new gains are generated. Bit 4 is
kept reserved/deprecated because successful current-validation retry is reported
through current-loop evidence, not `inner_warning_flags`. Persisted outer gains
from an earlier tune remain unchanged until retuned.

## Production-Motion Validation

Before accepting the production autotune path for a printer profile, run the
profile through this recipe on the live machine. It combines a per-axis tune
with a production motion matrix and an explicit robustness-gate confirmation;
a bench-only or single-axis tune is not a substitute before committing a
profile to production use.

### 1. Per-axis autotune

Run `FOCI_AUTOTUNE STEPPER=stepper_x` and `FOCI_AUTOTUNE STEPPER=stepper_y`
separately (no `ACTION=` needed for the production path), each after the
normal commissioning and homing prerequisites. Each invocation drives both
firmware dispatches internally -- `breakaway_seeded`, then an auto-issued
`stage_c_resume` -- and, on a full pass, deploys the conservative gain and
persists it. Stage-C reproduction is stochastic; an occasional `inconclusive`
result is expected and not a regression, and the command is simply re-run.

Confirm for each axis:

- The command completes without error and reports a full pass, not a
  robustness reject or fault. A reject or fault persists nothing and fails
  the command, and firmware de-energizes the motor; only a robustness safety
  fault additionally inhibits motor enable until re-commissioned.
- After `SAVE_CONFIG` (which restarts the firmware), `printer.cfg` (or the
  `SAVE_CONFIG` autosave block) carries `autotune_status = tuned` or
  `tuned_conservative` for that stepper, the tuned outer gains, and the
  provenance block (`autotune_probed_velocity_mrev_s`, `autotune_d_eq_q`,
  `autotune_confidence_q`, `autotune_band_lower_percent`/`_upper_percent`,
  `autotune_band_position_q`). `FOCI_AUTOTUNE` only stages these values via
  `configfile.set()`; they are not on disk until `SAVE_CONFIG` runs.

### 2. Production motion matrix

With both axes tuned, exercise production motion on the live CoreXY, not just
the autotune's own probe motion:

- X-only and Y-only straight moves.
- CoreXY diagonal moves (both axes commanded together).
- Direction reversals on each axis.
- Multiple commanded speeds and multiple accelerations, spanning the range the
  profile is expected to run at in production, not only the autotune's probed
  operating point.
- Both a warm state (immediately after tuning, motors already at temperature)
  and a cold state (after an idle/cool-down period, or after a fresh
  `FIRMWARE_RESTART` and re-home).

Across this matrix, watch for loss of sync between encoder and commanded
position, following-error faults, and any robustness safety fault.

### 3. Confirm the gate accepts the natural candidate

The robustness gate's IAE coefficient is a provisional, single-machine
calibration. As part of this run, explicitly confirm the gate accepts the
autotune's own natural candidate: the per-axis `FOCI_AUTOTUNE` runs above must
complete with a robustness pass, not a reject, on the gains the autotune
itself proposes (this is the on-target confirmation that the calibration
accepts a genuinely good candidate rather than spuriously rejecting one). If
the gate rejects a candidate that the motion matrix otherwise shows to be
sound, that is a finding to recalibrate the gate, not a reason to work around
it.

### Pass criteria

A profile is validated when, for both axes:

- `FOCI_AUTOTUNE` completes and persists `autotune_status = tuned` or
  `tuned_conservative` with a full provenance block.
- Production motion across the full speed, acceleration, and warm/cold matrix
  runs without loss-of-sync, following-error, or safety-fault events.
- No spurious robustness rejection of the natural candidate occurs.
- No connect-time "tuned below operating range" staleness warning is logged
  for the profile's actual operating velocity -- the probed velocity covers
  the configured operating range within the staleness margin.

### Where results are recorded

Record the run in the session logbook (`docs/logbook/YYYY-MM-DD.md`): which
axes and profile were tuned, the motion matrix exercised, and the gate
acceptance confirmation. The persisted outcome itself lives in `printer.cfg`'s
`[foci <stepper>]` sections -- `autotune_status`, the tuned outer gains, and
the provenance fields listed above -- which is the durable record read back at
every later connect.

## License

GPL-3.0. See `COPYING` at the repo root for the full text..
