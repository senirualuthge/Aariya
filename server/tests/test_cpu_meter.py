"""Regression tests for the shared CPU meter.

The bug this locks down: ``psutil.cpu_percent(interval=None)`` keeps ONE
process-wide baseline and every call resets it. With the analytics stream
(1 Hz per phone), the 2 s health broadcaster, the autonomy daemon, the
cognitive shards and the energy manager all sampling, each read measured a
sliver left over from somebody else's call. Two phones connected at once saw
the same machine as ``0.0%`` and ``100.0%`` in the same second, which is what
made the app's PROCESSOR card look laggy.

``cpu_meter`` derives percentages from cumulative ``cpu_times()`` counters, so
no consumer can steal another's measurement window.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

from server.infrastructure import cpu_meter

CpuTimes = namedtuple(
    "CpuTimes", "user nice system idle iowait irq softirq steal"
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def meter(monkeypatch):
    """Isolated meter with a controllable clock and counter table."""
    clock = FakeClock()
    counters = {"total": 1000.0, "idle": 900.0, "calls": 0, "percpu": []}

    def fake_cpu_times(percpu: bool = False):
        if percpu:
            return list(counters["percpu"])
        counters["calls"] += 1
        busy = counters["total"] - counters["idle"]
        return CpuTimes(
            user=busy, nice=0.0, system=0.0, idle=counters["idle"], iowait=0.0,
            irq=0.0, softirq=0.0, steal=0.0,
        )

    monkeypatch.setattr(cpu_meter.psutil, "cpu_times", fake_cpu_times)
    monkeypatch.setattr(cpu_meter.time, "monotonic", clock.monotonic)
    cpu_meter.reset()
    yield clock, counters
    cpu_meter.reset()


def test_first_call_is_a_baseline_and_later_calls_are_real(meter):
    clock, counters = meter

    assert cpu_meter.cpu_percent() == 0.0  # no previous snapshot yet

    # 200 ticks elapse, 100 of them busy → 50%.
    counters["idle"] += 100.0
    counters["total"] += 200.0
    clock.now += 2.0

    assert cpu_meter.cpu_percent() == 50.0


def test_simultaneous_consumers_share_one_reading(meter):
    """The bug: a second consumer must not re-measure a tiny slice."""
    clock, counters = meter

    cpu_meter.cpu_percent()  # baseline, warms the cache
    counters["calls"] = 0

    # Past the cache TTL: this call does the real computation.
    counters["idle"] += 100.0
    counters["total"] += 200.0
    clock.now += 2.0
    first = cpu_meter.cpu_percent()

    # A second consumer sampling moments later reuses it rather than
    # re-measuring a sliver of the same window.
    second = cpu_meter.cpu_percent()

    assert first == second == 50.0
    assert counters["calls"] == 1


def test_never_calls_psutil_cpu_percent(meter, monkeypatch):
    """Guards the fix itself: the shared-baseline API must not be used."""
    clock, counters = meter

    def boom(*args, **kwargs):
        raise AssertionError("psutil.cpu_percent must not be used for system CPU")

    monkeypatch.setattr(cpu_meter.psutil, "cpu_percent", boom)

    cpu_meter.cpu_percent()
    counters["total"] += 10.0
    clock.now += 2.0
    assert isinstance(cpu_meter.cpu_percent(), float)


def test_zero_or_negative_delta_reports_zero_not_garbage(meter):
    clock, _ = meter

    cpu_meter.cpu_percent()  # baseline
    clock.now += 2.0          # counters unchanged → d_total == 0
    assert cpu_meter.cpu_percent() == 0.0


def test_per_core_returns_one_value_per_core(meter):
    clock, counters = meter
    core = CpuTimes(user=10.0, nice=0.0, system=0.0, idle=90.0, iowait=0.0,
                    irq=0.0, softirq=0.0, steal=0.0)
    counters["percpu"] = [core, core]

    # First call establishes the per-core baseline (total 100, idle 90).
    assert cpu_meter.cpu_percent_per_core() == [0.0, 0.0]

    # Cumulative counters move forward: total 100 → 200, idle 90 → 140.
    # 100 new ticks, 50 of them idle → 50% busy on every core.
    busy = CpuTimes(user=60.0, nice=0.0, system=0.0, idle=140.0, iowait=0.0,
                    irq=0.0, softirq=0.0, steal=0.0)
    counters["percpu"] = [busy, busy]
    clock.now += 2.0

    assert cpu_meter.cpu_percent_per_core() == [50.0, 50.0]
