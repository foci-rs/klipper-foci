"""Tests for firmware stepper-event diagnostics."""

from tests.mocks import MockGCode, make_driver


def test_stepper_event_handler_formats_known_reason_for_gcode_output():
    driver = make_driver(stepper_name="stepper_x")
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    driver._handle_stepper_event(
        {
            "reason": 4,
            "channel": 0,
            "position": 6465,
            "clock": 123456,
            "timer_active": 1,
            "queue_len": 17,
            "direction": 1,
            "data0": 20,
            "data1": 45150,
        }
    )

    assert gcode._responses == [
        "FOCI_STEPPER_EVENT stepper_x reason=trsync_stop(4) channel=0 "
        "pos=6465 clock=123456 timer_active=1 queue_len=17 dir=1 "
        "data0=20 data1=45150"
    ]


def test_stepper_event_handler_formats_unknown_reason_without_crashing():
    driver = make_driver(stepper_name="stepper_y")
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    driver._handle_stepper_event(
        {
            "reason": 99,
            "channel": 0,
            "position": -13,
            "clock": 7,
            "timer_active": 0,
            "queue_len": 0,
            "direction": 0,
            "data0": 0,
            "data1": 0,
        }
    )

    assert "reason=unknown(99)" in gcode._responses[-1]
    assert "stepper_y" in gcode._responses[-1]


def test_stepper_perf_event_handler_formats_fatal_snapshot():
    driver = make_driver(stepper_name="stepper_x")
    gcode = MockGCode()
    driver.printer._objects["gcode"] = gcode

    driver._handle_stepper_perf_event(
        {
            "reason": 2,
            "channel": 0,
            "clock": 197311339,
            "sample_count": 410,
            "crit_count": 202,
            "crit_max_cycles": 200000,
            "crit_max_site": 1,
            "crit_over_10us": 10,
            "crit_over_50us": 5,
            "crit_over_100us": 3,
            "crit_over_1000us": 1,
            "queue_step_count": 90,
            "queue_step_max_cycles": 180000,
            "tim5_activation_count": 208,
            "tim5_irq_max_cycles": 2400,
            "tim5_dispatch_max_cycles": 2100,
            "tim5_dispatch_max_cycles_events": 5,
            "tim5_events_max_per_irq": 13,
            "tim5_event_count_total": 721,
            "tim5_defer_count": 6,
            "tim5_empty_count": 2,
            "tim5_events_last_activation": 14,
            "tim5_burst_cycles_per_event_max": 1345,
            "tim5_burst_cycles_per_event_max_cycles": 2690,
            "tim5_burst_cycles_per_event_max_events": 2,
            "tim5_burst_cycles_per_event_floor3_max": 900,
            "tim5_entry_latency_max_ticks": 8400,
            "tim5_pop_lateness_max_ticks": 72,
            "scheduler_cycles_max": 555,
            "scheduler_cycles_events_at_max": 4,
            "scheduler_cycles_per_event_max": 111,
            "scheduler_cycles_per_event_max_cycles": 555,
            "scheduler_cycles_per_event_max_events": 5,
            "scheduler_cycles_per_event_floor3_max": 111,
            "scheduler_full_count": 2,
            "stepper_load_lateness_max_ticks": 1234,
            "stepper_load_lateness_last_ticks": -12,
            "build_trace_enabled": 1,
        }
    )

    assert gcode._responses == [
        "FOCI_STEPPER_PERF_EVENT stepper_x reason=missed_deadline_load(2) "
        "channel=0 clock=197311339 sample_count=410 crit_count=202 "
        "crit_max_cycles=200000 crit_max_site=1 crit_max_us=1190 "
        "crit_over_10us=10 crit_over_50us=5 crit_over_100us=3 "
        "crit_over_1000us=1 queue_step_count=90 "
        "queue_step_max_cycles=180000 queue_step_max_us=1071 "
        "tim5_activation_count=208 tim5_irq_max_cycles=2400 tim5_irq_max_us=14 "
        "tim5_dispatch_max_cycles=2100 tim5_dispatch_max_us=12 "
        "tim5_dispatch_max_cycles_events=5 tim5_events_max_per_irq=13 "
        "tim5_event_count_total=721 "
        "tim5_defer_count=6 tim5_empty_count=2 "
        "tim5_events_last_activation=14 tim5_burst_cycles_per_event_max=1345 "
        "tim5_burst_cycles_per_event_max_cycles=2690 "
        "tim5_burst_cycles_per_event_max_events=2 "
        "tim5_burst_cycles_per_event_floor3_max=900 "
        "tim5_entry_latency_max_ticks=8400 tim5_pop_lateness_max_ticks=72 "
        "scheduler_cycles_max=555 scheduler_cycles_events_at_max=4 "
        "scheduler_cycles_per_event_max=111 "
        "scheduler_cycles_per_event_max_cycles=555 "
        "scheduler_cycles_per_event_max_events=5 "
        "scheduler_cycles_per_event_floor3_max=111 scheduler_full_count=2 "
        "stepper_load_lateness_max_ticks=1234 "
        "stepper_load_lateness_last_ticks=-12 build_trace_enabled=1"
    ]
