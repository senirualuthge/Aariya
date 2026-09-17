"""
Conscious Loop — the always-running observe → reflect → plan cycle.

Runs on a periodic tick. Sources (observation providers) are registered as
async callables returning a dict. Reflections feed a downstream planner. The
loop is intentionally bounded so it is safe to run forever.
"""

import asyncio
import logging
from typing import Callable, Dict, Any, Awaitable, Optional

logger = logging.getLogger("aariya.conscious_loop")

Source = Callable[[], Awaitable[Dict[str, Any]]]


class ConsciousLoop:
    def __init__(self, reflection, planner, interval: float = 5.0,
                 on_tick: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self.reflection = reflection
        self.planner = planner
        self.interval = interval
        # Optional async callback invoked after every tick with the plan
        # result — how the daemon turns observations into real events.
        self.on_tick = on_tick
        self.running = False
        self.last_result: Dict[str, Any] = {}
        self.sources: Dict[str, Source] = {}
        self._observation_cache: Dict[str, Any] = {}

    def register_source(self, name: str, source: Source) -> None:
        self.sources[name] = source

    async def observe(self) -> Dict[str, Any]:
        observations = {}
        for name, source in self.sources.items():
            try:
                observations[name] = await source()
            except Exception as e:
                logger.warning(f"[conscious_loop] source {name} failed: {e}")
                observations[name] = {"error": str(e)}
        self._observation_cache = observations
        return observations

    async def reflect(self) -> Dict[str, Any]:
        if not self._observation_cache:
            return {"insights": [], "summary": "no data"}
        insights = []
        for name, data in self._observation_cache.items():
            if isinstance(data, dict) and data.get("needs_attention"):
                insights.append({"source": name, "detail": data.get("detail", "")})
        return {"insights": insights, "summary": self._summarize(insights)}

    @staticmethod
    def _summarize(insights) -> str:
        return f"{len(insights)} source(s) need attention" if insights else "all clear"

    async def plan(self) -> Dict[str, Any]:
        reflection = await self.reflect()
        if not reflection["insights"]:
            return {"actions": ["continue_monitoring"]}
        if self.planner is None:
            # Observation-only loop (daemon mode): surface insights without
            # planning — a tick must never crash for lack of a planner.
            return {"actions": [], "based_on": reflection["summary"]}
        actions = []
        for i in reflection["insights"]:
            plan = self.planner.generate_plan(f"handle: {i['source']}")
            actions.append({"source": i["source"], "plan": plan})
        return {"actions": actions, "based_on": reflection["summary"]}

    async def tick(self) -> Dict[str, Any]:
        await self.observe()
        reflection = await self.reflect()
        result = await self.plan()
        # on_tick consumers (the autonomy daemon) need the raw insights and
        # summary — plan() alone doesn't carry them.
        self.last_result = {
            **result,
            "insights": reflection.get("insights", []),
            "summary": reflection.get("summary", ""),
        }
        if self.on_tick is not None:
            try:
                out = self.on_tick(self.last_result)
                if asyncio.iscoroutine(out):
                    await out
            except Exception as e:
                logger.warning(f"[conscious_loop] on_tick failed: {e}")
        return self.last_result

    async def run(self):
        self.running = True
        while self.running:
            try:
                await self.tick()
            except Exception as e:
                logger.error(f"[conscious_loop] tick error: {e}")
            await asyncio.sleep(self.interval)

    def stop(self):
        self.running = False
