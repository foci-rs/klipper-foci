"""Live controller control commands for FOCI host workflows."""

from __future__ import annotations


class ControlsWorkflow:
    """Apply live controller mutators requested through G-code."""

    def __init__(self, driver) -> None:
        self.driver = driver

    def set_gains(self, gcmd) -> None:
        """Set outer-loop gains for live bringup debugging.

        Parameters are floating-point gain values. For example, `VELOCITY_P=2.0`
        writes raw Q8.8 value 512 and `POSITION_P=1.0` writes raw value 256.
        Values are applied immediately and kept in memory for the current Klipper
        session, but are not persisted to printer.cfg.
        """
        velocity_p = self._get_outer_gain(gcmd, "VELOCITY_P")
        velocity_i = self._get_outer_gain(gcmd, "VELOCITY_I")
        position_p = self._get_outer_gain(gcmd, "POSITION_P")
        position_i = self._get_outer_gain(gcmd, "POSITION_I")

        self.driver.set_position_gains_cmd.send(
            [self.driver.oid, position_p, position_i, velocity_p, velocity_i]
        )

        self.driver.pid_velocity_p = velocity_p
        self.driver.pid_velocity_i = velocity_i
        self.driver.pid_position_p = position_p
        self.driver.pid_position_i = position_i
        if self.driver.state.active_gains is not None:
            self.driver.state.active_gains["velocity_p"] = velocity_p
            self.driver.state.active_gains["velocity_i"] = velocity_i
            self.driver.state.active_gains["position_p"] = position_p
            self.driver.state.active_gains["position_i"] = position_i

        gcmd.respond_info(
            "FOCI %s debug gains set: vel_p=%d/256 vel_i=%d/256"
            " pos_p=%d/256 pos_i=%d/256"
            % (self.driver.name, velocity_p, velocity_i, position_p, position_i)
        )

    def set_inner_gains(self, gcmd) -> None:
        """Set inner current-loop gains for live bringup debugging.

        Parameters are raw TMC4671 register values. P gains are Q8.8
        numerators. Current I gains are also Q8.8 while
        CONFIG_ADVANCED_PI_REPRESENT remains at its default 0; in advanced PI
        mode their effective zero factor is raw/65536 per PWM sample. Values
        are applied immediately and kept in memory for the current Klipper
        session, but are not persisted to printer.cfg.
        """
        flux_p = gcmd.get_int("FLUX_P", minval=0, maxval=65535)
        flux_i = gcmd.get_int("FLUX_I", minval=0, maxval=65535)
        torque_p = gcmd.get_int("TORQUE_P", minval=0, maxval=65535)
        torque_i = gcmd.get_int("TORQUE_I", minval=0, maxval=65535)

        self.driver.set_pid_gains_cmd.send(
            [self.driver.oid, flux_p, flux_i, torque_p, torque_i]
        )

        if self.driver.state.active_gains is not None:
            self.driver.state.active_gains["flux_p"] = flux_p
            self.driver.state.active_gains["flux_i"] = flux_i
            self.driver.state.active_gains["torque_p"] = torque_p
            self.driver.state.active_gains["torque_i"] = torque_i

        gcmd.respond_info(
            "FOCI %s inner gains set: flux_p=%d/256"
            " flux_i=%d(q8.8=%.3f zero=%d/65536)"
            " torque_p=%d/256 torque_i=%d(q8.8=%.3f zero=%d/65536)"
            % (
                self.driver.name,
                flux_p,
                flux_i,
                flux_i * 2**-8,
                flux_i,
                torque_p,
                torque_i,
                torque_i * 2**-8,
                torque_i,
            )
        )

    def set_current(self, gcmd) -> None:
        """Set run current for live bringup debugging.

        RUN_CURRENT is in amps RMS, matching the printer.cfg convention. The
        value is applied immediately and kept in memory for the current Klipper
        session, but is not persisted to printer.cfg.
        """
        run_current = gcmd.get_float("RUN_CURRENT", minval=0.0, maxval=5.0)
        if run_current <= 0.0:
            raise gcmd.error("FOCI %s: RUN_CURRENT must be above 0" % self.driver.name)

        run_ma = int(run_current * 1000.0 + 0.5)
        self.driver.set_current_cmd.send([self.driver.oid, run_ma])
        self.driver.run_current = run_current

        gcmd.respond_info(
            "FOCI %s run current set: run_current=%.3fA run_ma=%d"
            % (self.driver.name, run_current, run_ma)
        )

    def set_velocity_feedforward(self, gcmd) -> None:
        """Set velocity feedforward multiplier for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        multiplier = gcmd.get_int(
            "MULTIPLIER",
            self.driver.velocity_feedforward_multiplier,
            minval=0,
            maxval=65535,
        )

        self.driver.set_velocity_feedforward_cmd.send(
            [self.driver.oid, enable, multiplier]
        )
        self.driver.velocity_feedforward = enable != 0
        self.driver.velocity_feedforward_multiplier = multiplier

        gcmd.respond_info(
            "FOCI %s velocity feedforward set: enable=%d multiplier=%d"
            % (self.driver.name, enable, multiplier)
        )

    def _get_outer_gain(self, gcmd, key: str) -> int:
        """Read a floating-point gain parameter and convert it to raw Q8.8."""
        value = gcmd.get_float(key, minval=0.0, maxval=32767.0 / 256.0)
        return min(32767, int(value * 256.0 + 0.5))
