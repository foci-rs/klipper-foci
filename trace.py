"""Legacy Klipper/G-code trace parsing and summary helpers.

This module backs the existing ``FOCI_TRACE_*`` command path. The USB trace
stream is the long-term trace path; this module remains until those workflows
cover the legacy G-code trace use cases.
"""

from __future__ import annotations

import math
import struct

TRACE_FAST_HEADERS = [
    "tick",
    "phase",
    "flags",
    "pos_tgt",
    "pos_act",
    "trq_act",
    "flx_act",
    "pidout_vel",
    "status",
    "abn",
]

TRACE_FULL_HEADERS = TRACE_FAST_HEADERS + [
    "trq_tgt",
    "flx_tgt",
    "vel_ofs",
    "esum_pos",
    "esum_vel",
    "esum_trq",
]

TRACE_VELOCITY_HEADERS = TRACE_FAST_HEADERS + [
    "pos_err",
    "pidout_trq",
    "pidout_flx",
    "pidin_vel",
    "vel_actual",
    "vel_ofs",
]

TRACE_HOLD_HEADERS = TRACE_FAST_HEADERS + [
    "pidout_trq",
    "pidout_flx",
    "foc_uq",
    "foc_ud",
    "foc_uq_lim",
    "foc_ud_lim",
    "esum_trq",
    "esum_flx",
]

TRACE_FINAL_SETTLE_WINDOW = 30


def _range_metric(samples: list[list[int]], idx: int) -> dict[str, int]:
    values = [row[idx] for row in samples]
    return {
        "min": min(values),
        "max": max(values),
        "final": values[-1],
        "nonzero": sum(1 for value in values if value != 0),
    }


def _range_float_metric(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "final": 0.0}
    return {
        "min": min(values),
        "max": max(values),
        "final": values[-1],
    }


def _phase_error_metric(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "min": 0, "max": 0, "mean": 0.0, "max_abs": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "max_abs": max(values, key=lambda value: abs(value)),
    }


def _settle_metric(samples: list[list[int]], idx: int) -> dict[str, float | int]:
    values = [row[idx] for row in samples]
    square_sum = sum(value * value for value in values)
    return {
        "rms": math.sqrt(square_sum / len(values)),
        "max_abs": max(abs(value) for value in values),
        "final": values[-1],
        "nonzero": sum(1 for value in values if value != 0),
    }


def _position_error_metric(
    errors: list[int], samples: list[list[int]], tick_idx: int
) -> dict[str, int]:
    max_abs_error = max(errors, key=lambda value: abs(value))
    max_abs_error_idx = errors.index(max_abs_error)
    return {
        "min": min(errors),
        "max": max(errors),
        "final": errors[-1],
        "max_abs": max_abs_error,
        "max_abs_tick": samples[max_abs_error_idx][tick_idx],
    }


def _format_metric_value(value: float | int) -> str:
    if isinstance(value, float):
        return ("%.3f" % value).rstrip("0").rstrip(".")
    return str(value)


def _format_phase_error_metric(name: str, metric: dict[str, float | int]) -> str:
    return "%s(n=%d min=%d max=%d mean=%s max_abs=%d)" % (
        name,
        metric["count"],
        metric["min"],
        metric["max"],
        _format_metric_value(metric["mean"]),
        metric["max_abs"],
    )


def _format_settle_metric(name: str, metric: dict[str, float | int]) -> str:
    return "%s(rms=%s max_abs=%d final=%d)" % (
        name,
        _format_metric_value(metric["rms"]),
        metric["max_abs"],
        metric["final"],
    )


def _trace_summary_metrics(
    samples: list[list[int]],
    headers: list[str],
    expected_tick_step: int,
) -> dict:
    """Compute compact trace metrics from parsed trace rows."""
    columns = {name: idx for idx, name in enumerate(headers)}
    tick_idx = columns["tick"]
    pos_tgt_idx = columns["pos_tgt"]
    pos_act_idx = columns["pos_act"]
    pos_err_idx = columns.get("pos_err")

    errors = [row[pos_tgt_idx] - row[pos_act_idx] for row in samples]
    hardware_errors = (
        [row[pos_err_idx] for row in samples] if pos_err_idx is not None else []
    )

    duplicate_ticks = 0
    missed_samples = 0
    out_of_order_ticks = 0
    derived_target_velocities = []
    derived_actual_velocities = []
    derived_velocity_errors = []
    phase_error_values = {"accel": [], "cruise": [], "decel": []}
    hardware_phase_error_values = {"accel": [], "cruise": [], "decel": []}
    prev_target_velocity = None
    prev = samples[0]
    for row in samples[1:]:
        delta_tick = row[tick_idx] - prev[tick_idx]
        if delta_tick == 0:
            duplicate_ticks += 1
        elif delta_tick < 0:
            out_of_order_ticks += 1
        else:
            if delta_tick > expected_tick_step:
                missed_samples += (delta_tick - 1) // expected_tick_step
            delta_target = row[pos_tgt_idx] - prev[pos_tgt_idx]
            delta_actual = row[pos_act_idx] - prev[pos_act_idx]
            target_velocity = delta_target / delta_tick
            actual_velocity = delta_actual / delta_tick
            derived_target_velocities.append(target_velocity)
            derived_actual_velocities.append(actual_velocity)
            derived_velocity_errors.append(actual_velocity - target_velocity)

            if target_velocity != 0 and prev_target_velocity is not None:
                target_accel = target_velocity - prev_target_velocity
                position_error = row[pos_tgt_idx] - row[pos_act_idx]
                hardware_position_error = (
                    row[pos_err_idx] if pos_err_idx is not None else None
                )
                if target_velocity * target_accel > 0:
                    phase_error_values["accel"].append(position_error)
                    if hardware_position_error is not None:
                        hardware_phase_error_values["accel"].append(
                            hardware_position_error
                        )
                elif target_velocity * target_accel < 0:
                    phase_error_values["decel"].append(position_error)
                    if hardware_position_error is not None:
                        hardware_phase_error_values["decel"].append(
                            hardware_position_error
                        )
                else:
                    phase_error_values["cruise"].append(position_error)
                    if hardware_position_error is not None:
                        hardware_phase_error_values["cruise"].append(
                            hardware_position_error
                        )
            prev_target_velocity = target_velocity
        prev = row

    metrics = {
        "sample_count": len(samples),
        "tick_start": samples[0][tick_idx],
        "tick_end": samples[-1][tick_idx],
        "expected_tick_step": expected_tick_step,
        "duplicate_ticks": duplicate_ticks,
        "missed_samples": missed_samples,
        "out_of_order_ticks": out_of_order_ticks,
        "position_error": _position_error_metric(errors, samples, tick_idx),
    }

    if hardware_errors:
        metrics["hardware_position_error"] = _position_error_metric(
            hardware_errors, samples, tick_idx
        )

    metrics["derived_target_velocity"] = _range_float_metric(derived_target_velocities)
    metrics["derived_actual_velocity"] = _range_float_metric(derived_actual_velocities)
    metrics["derived_velocity"] = metrics["derived_actual_velocity"]
    metrics["derived_velocity_error"] = _range_float_metric(derived_velocity_errors)
    metrics["position_error_by_motion_phase"] = {
        "accel": _phase_error_metric(phase_error_values["accel"]),
        "cruise": _phase_error_metric(phase_error_values["cruise"]),
        "decel": _phase_error_metric(phase_error_values["decel"]),
    }
    if hardware_errors:
        metrics["hardware_position_error_by_motion_phase"] = {
            "accel": _phase_error_metric(hardware_phase_error_values["accel"]),
            "cruise": _phase_error_metric(hardware_phase_error_values["cruise"]),
            "decel": _phase_error_metric(hardware_phase_error_values["decel"]),
        }

    for field in (
        "trq_act",
        "flx_act",
        "pidin_vel",
        "pidout_vel",
        "vel_actual",
        "vel_ofs",
        "pidout_trq",
        "pidout_flx",
        "foc_uq",
        "foc_ud",
        "foc_uq_lim",
        "foc_ud_lim",
        "esum_trq",
        "esum_flx",
    ):
        if field in columns:
            metrics[field] = _range_metric(samples, columns[field])

    settle_samples = samples[-TRACE_FINAL_SETTLE_WINDOW:]
    final_settle = {
        "window_size": TRACE_FINAL_SETTLE_WINDOW,
        "sample_count": len(settle_samples),
    }
    for field in (
        "pos_err",
        "pidout_vel",
        "pidout_trq",
        "vel_actual",
        "trq_act",
        "flx_act",
        "foc_uq_lim",
        "foc_ud_lim",
        "esum_trq",
        "esum_flx",
    ):
        if field in columns:
            final_settle[field] = _settle_metric(settle_samples, columns[field])
    if len(final_settle) > 2:
        metrics["final_settle"] = final_settle

    if "status" in columns:
        status_values = [row[columns["status"]] for row in samples]
        metrics["status"] = {
            "unique": sorted(set(status_values)),
            "pid_v_output_limit_samples": sum(
                1 for value in status_values if value & (1 << 7)
            ),
        }

    return metrics


def _format_trace_summary(
    name: str,
    samples: list[list[int]],
    headers: list[str],
    preset_name: str,
    sample_period_us: int,
    dropped: int,
    expected_tick_step: int,
) -> list[str]:
    """Format compact trace metrics for G-code responses."""
    metrics = _trace_summary_metrics(samples, headers, expected_tick_step)
    effective_sample_period_us = sample_period_us * expected_tick_step
    lines = [
        "FOCI %s trace summary: %d samples, %s preset, %dus tick, %dus samples"
        % (
            name,
            metrics["sample_count"],
            preset_name,
            sample_period_us,
            effective_sample_period_us,
        )
    ]
    lines.append(
        "ticks: start=%d end=%d expected_step=%d duplicate=%d missed=%d"
        " out_of_order=%d dropped=%d"
        % (
            metrics["tick_start"],
            metrics["tick_end"],
            metrics["expected_tick_step"],
            metrics["duplicate_ticks"],
            metrics["missed_samples"],
            metrics["out_of_order_ticks"],
            dropped,
        )
    )

    position_error = metrics["position_error"]
    lines.append(
        "position_error_counts: min=%d max=%d final=%d max_abs=%d at_tick=%d"
        % (
            position_error["min"],
            position_error["max"],
            position_error["final"],
            position_error["max_abs"],
            position_error["max_abs_tick"],
        )
    )

    phase_errors = metrics["position_error_by_motion_phase"]
    lines.append(
        "position_error_by_phase: %s %s %s"
        % (
            _format_phase_error_metric("accel", phase_errors["accel"]),
            _format_phase_error_metric("cruise", phase_errors["cruise"]),
            _format_phase_error_metric("decel", phase_errors["decel"]),
        )
    )

    if "hardware_position_error" in metrics:
        hardware_position_error = metrics["hardware_position_error"]
        lines.append(
            "hardware_position_error_counts: min=%d max=%d final=%d max_abs=%d"
            " at_tick=%d"
            % (
                hardware_position_error["min"],
                hardware_position_error["max"],
                hardware_position_error["final"],
                hardware_position_error["max_abs"],
                hardware_position_error["max_abs_tick"],
            )
        )

    if "hardware_position_error_by_motion_phase" in metrics:
        phase_errors = metrics["hardware_position_error_by_motion_phase"]
        lines.append(
            "hardware_position_error_by_phase: %s %s %s"
            % (
                _format_phase_error_metric("accel", phase_errors["accel"]),
                _format_phase_error_metric("cruise", phase_errors["cruise"]),
                _format_phase_error_metric("decel", phase_errors["decel"]),
            )
        )

    derived_target_velocity = metrics["derived_target_velocity"]
    lines.append(
        "derived_target_velocity_counts_per_tick: min=%s max=%s final=%s"
        % (
            _format_metric_value(derived_target_velocity["min"]),
            _format_metric_value(derived_target_velocity["max"]),
            _format_metric_value(derived_target_velocity["final"]),
        )
    )

    derived_velocity = metrics["derived_velocity"]
    lines.append(
        "derived_actual_velocity_counts_per_tick: min=%s max=%s final=%s"
        % (
            _format_metric_value(derived_velocity["min"]),
            _format_metric_value(derived_velocity["max"]),
            _format_metric_value(derived_velocity["final"]),
        )
    )

    derived_velocity_error = metrics["derived_velocity_error"]
    lines.append(
        "derived_velocity_error_counts_per_tick: min=%s max=%s final=%s"
        % (
            _format_metric_value(derived_velocity_error["min"]),
            _format_metric_value(derived_velocity_error["max"]),
            _format_metric_value(derived_velocity_error["final"]),
        )
    )

    for field in (
        "trq_act",
        "flx_act",
        "pidin_vel",
        "pidout_vel",
        "vel_actual",
        "vel_ofs",
        "pidout_trq",
        "pidout_flx",
        "foc_uq",
        "foc_ud",
        "foc_uq_lim",
        "foc_ud_lim",
        "esum_trq",
        "esum_flx",
    ):
        if field in metrics:
            metric = metrics[field]
            lines.append(
                "%s: min=%d max=%d final=%d nonzero=%d"
                % (
                    field,
                    metric["min"],
                    metric["max"],
                    metric["final"],
                    metric["nonzero"],
                )
            )

    if "final_settle" in metrics:
        final_settle = metrics["final_settle"]
        settle_fields = []
        for field in (
            "pos_err",
            "pidout_vel",
            "pidout_trq",
            "vel_actual",
            "trq_act",
            "flx_act",
            "foc_uq_lim",
            "foc_ud_lim",
            "esum_trq",
            "esum_flx",
        ):
            if field in final_settle:
                settle_fields.append(_format_settle_metric(field, final_settle[field]))
        if settle_fields:
            lines.append(
                "final_settle_last_%d: n=%d %s"
                % (
                    final_settle["window_size"],
                    final_settle["sample_count"],
                    " ".join(settle_fields),
                )
            )

    if "status" in metrics:
        status = metrics["status"]
        unique = ",".join("0x%08x" % value for value in status["unique"])
        lines.append(
            "status: unique=%s pid_v_output_limit_samples=%d"
            % (unique, status["pid_v_output_limit_samples"])
        )

    return lines


class LegacyTraceWorkflow:
    """Legacy G-code trace capture workflow pending deprecation."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.trace_info: dict | None = None
        self.trace_info_received = False

    def handle_trace_info_result(self, params: dict) -> None:
        """Handle foci_trace_info_result response from firmware."""
        self.trace_info = params
        self.trace_info_received = True

    def trace_start(self, gcmd) -> None:
        """Start per-tick trace capture for the selected stepper."""
        preset_name = gcmd.get("PRESET", "full").lower()
        presets = {"fast": 0, "full": 1, "velocity": 2, "hold": 3}
        if preset_name not in presets:
            raise gcmd.error(
                "FOCI %s: unknown trace preset '%s' "
                "(expected fast, full, velocity, or hold)"
                % (self.driver.name, preset_name)
            )
        self.driver.protocol.commands.trace_start.send(
            [self.driver.oid, presets[preset_name]]
        )
        gcmd.respond_info(
            "FOCI %s trace capture started (%s preset)"
            % (self.driver.name, preset_name)
        )

    def trace_stop(self, gcmd) -> None:
        """Stop per-tick trace capture for the selected stepper."""
        self.driver.protocol.commands.trace_stop.send([self.driver.oid])
        gcmd.respond_info("FOCI %s trace capture stopped" % self.driver.name)

    def trace(self, gcmd) -> None:
        """Fetch and display the trace capture buffer."""
        format_name = gcmd.get("FORMAT", "table").lower()
        phase_filter = gcmd.get_int("PHASE", None)

        self.trace_info = None
        self.trace_info_received = False
        self.driver.protocol.commands.trace_info.send([self.driver.oid])

        reactor = self.driver.printer.get_reactor()
        deadline = reactor.monotonic() + 5.0
        while not self.trace_info_received:
            if reactor.monotonic() > deadline:
                raise gcmd.error("FOCI %s: trace info timed out" % self.driver.name)
            reactor.pause(reactor.monotonic() + 0.05)

        info = self.trace_info
        state = info.get("state", 0)
        count = info.get("count", 0)
        generation = info.get("generation", 0)

        if state != 2 or count == 0:
            gcmd.respond_info("FOCI %s: no trace data available" % self.driver.name)
            return

        preset = info.get("preset", 0)
        dropped = info.get("dropped", 0)
        sample_period = info.get("sample_period_us", 1000)

        if preset == 1:  # Full
            sample_size = 48
            fmt = "<HBBiiIiIiIiiii"
            headers = TRACE_FULL_HEADERS
        elif preset == 2:  # Velocity
            sample_size = 52
            fmt = "<HBBiiIiIiiiiiii"
            headers = TRACE_VELOCITY_HEADERS
        elif preset == 3:  # Hold
            sample_size = 52
            fmt = "<HBBiiIiIiiiIIii"
            headers = TRACE_HOLD_HEADERS
        else:  # Fast
            sample_size = 28
            fmt = "<HBBiiIiIi"
            headers = TRACE_FAST_HEADERS

        def _i16(val: int) -> int:
            """Convert unsigned 16-bit half to signed i16."""
            return val - 0x10000 if val >= 0x8000 else val

        samples = []
        for i in range(count):
            params = self.driver.protocol.commands.trace_fetch.send(
                [self.driver.oid, i, generation]
            )
            status = params.get("status", 2)
            if status != 0:
                status_names = {1: "capture still active", 2: "invalid"}
                gcmd.respond_info(
                    "FOCI %s: trace fetch aborted at offset %d: %s"
                    % (
                        self.driver.name,
                        i,
                        status_names.get(status, "unknown"),
                    )
                )
                return
            data = params.get("data", b"")
            if len(data) != sample_size:
                gcmd.respond_info(
                    "FOCI %s: unexpected sample size %d (expected %d)"
                    % (self.driver.name, len(data), sample_size)
                )
                return
            fields = struct.unpack(fmt, data)

            if preset == 1:
                row = list(fields[:3])
                row.extend(list(fields[3:5]))
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))
                row.append(_i16(tf_act & 0xFFFF))
                row.extend(list(fields[6:9]))
                tf_tgt = fields[9]
                row.append(_i16((tf_tgt >> 16) & 0xFFFF))
                row.append(_i16(tf_tgt & 0xFFFF))
                row.extend(list(fields[10:]))
            elif preset == 2:
                row = list(fields[:3])
                row.extend(list(fields[3:5]))
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))
                row.append(_i16(tf_act & 0xFFFF))
                row.extend(list(fields[6:9]))
                row.extend(list(fields[9:]))
            elif preset == 3:
                row = list(fields[:3])
                row.extend(list(fields[3:5]))
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))
                row.append(_i16(tf_act & 0xFFFF))
                row.extend(list(fields[6:9]))
                row.extend(list(fields[9:11]))
                foc_uq_ud = fields[11]
                row.append(_i16((foc_uq_ud >> 16) & 0xFFFF))
                row.append(_i16(foc_uq_ud & 0xFFFF))
                foc_uq_ud_limited = fields[12]
                row.append(_i16((foc_uq_ud_limited >> 16) & 0xFFFF))
                row.append(_i16(foc_uq_ud_limited & 0xFFFF))
                row.extend(list(fields[13:]))
            else:
                row = list(fields[:3])
                row.extend(list(fields[3:5]))
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))
                row.append(_i16(tf_act & 0xFFFF))
                row.extend(list(fields[6:]))
            samples.append(row)

        if phase_filter is not None:
            phase_col = 1
            samples = [s for s in samples if s[phase_col] == phase_filter]

        if not samples:
            gcmd.respond_info("FOCI %s: no samples match filter" % self.driver.name)
            return

        preset_names = {1: "full", 2: "velocity", 3: "hold"}
        preset_name = preset_names.get(preset, "fast")
        expected_tick_step = {1: 2, 2: 2, 3: 10}.get(preset, 1)
        header = "FOCI %s trace: %d samples" % (self.driver.name, len(samples))
        if dropped > 0:
            header += " (%d dropped)" % dropped
        header += ", %s preset, %dus period" % (preset_name, sample_period)

        if format_name == "summary":
            lines = _format_trace_summary(
                self.driver.name,
                samples,
                headers,
                preset_name,
                sample_period,
                dropped,
                expected_tick_step,
            )
        elif format_name == "csv":
            lines = [header, ",".join(headers)]
            for row in samples:
                lines.append(",".join(str(v) for v in row))
        else:
            lines = [header]
            col_widths = [max(len(h), 8) for h in headers]
            lines.append("  ".join(h.rjust(w) for h, w in zip(headers, col_widths)))
            for row in samples:
                lines.append(
                    "  ".join(str(v).rjust(w) for v, w in zip(row, col_widths))
                )

        gcmd.respond_info("\n".join(lines))
