"""Planning Engine nativo para agentes.

Implementa un sistema de planificación con ciclo plan → execute → verify
para descomponer objetivos de alto nivel en pasos ejecutables.

Cada plan tiene:
- Goals: objetivos de alto nivel
- Steps: pasos atómicos ejecutables
- Dependencies: entre pasos
- Verification: criterios de éxito por paso
- Replanning: ajuste dinámico ante fallos

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────

MAX_PLAN_STEPS = 20
MAX_RETRIES_PER_STEP = 3
MAX_REPLANS = 3
STEP_TIMEOUT_SECS = 300


# ── Tipos ────────────────────────────────────────────────────


class StepStatus(str, Enum):
    """Estado de un paso del plan."""
    PENDING = "pending"
    BLOCKED = "blocked"       # Esperando dependencias
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    """Estado global del plan."""
    DRAFT = "draft"           # Plan creado pero no ejecutando
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    REPLANNING = "replanning"


@dataclass
class PlanStep:
    """Paso individual de un plan."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    description: str = ""
    action: str = ""              # Acción a ejecutar (tool name, code, etc.)
    action_args: Dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    depends_on: List[str] = field(default_factory=list)  # IDs de pasos previos
    verification: str = ""        # Criterio de éxito
    output: str = ""              # Resultado de la ejecución
    error: str = ""               # Error si falló
    retries: int = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_secs: float = 0.0

    @property
    def is_terminal(self) -> bool:
        return self.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "action": self.action,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "verification": self.verification,
            "output": self.output[:500] if self.output else "",
            "error": self.error[:200] if self.error else "",
            "retries": self.retries,
            "duration_secs": self.duration_secs,
        }


@dataclass
class Plan:
    """Plan de ejecución completo."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    goal: str = ""
    context: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    steps: List[PlanStep] = field(default_factory=list)
    replan_count: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_secs: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Queries ────────────────────────────────────────────

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def pending_steps(self) -> List[PlanStep]:
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def ready_steps(self) -> List[PlanStep]:
        """Pasos que pueden ejecutarse (dependencias satisfechas)."""
        completed_ids = {s.id for s in self.steps if s.status == StepStatus.COMPLETED}
        ready: List[PlanStep] = []
        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue
            if all(dep in completed_ids for dep in step.depends_on):
                ready.append(step)
        return ready

    def is_complete(self) -> bool:
        return all(s.is_terminal for s in self.steps)

    def has_failures(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def progress(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for step in self.steps:
            counts[step.status.value] = counts.get(step.status.value, 0) + 1
        counts["total"] = len(self.steps)
        return counts

    # ── Serialization ──────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.value,
            "progress": self.progress(),
            "steps": [s.to_dict() for s in self.steps],
            "replan_count": self.replan_count,
            "duration_secs": self.duration_secs,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Plan: {self.goal}",
            f"Estado: {self.status.value} | Progreso: {self._progress_bar()}",
            "",
        ]
        for i, step in enumerate(self.steps, 1):
            icon = {
                StepStatus.PENDING: "⬜",
                StepStatus.BLOCKED: "🔒",
                StepStatus.IN_PROGRESS: "🔄",
                StepStatus.COMPLETED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.SKIPPED: "⏭️",
            }.get(step.status, "⬜")

            dep_text = f" (depende de: {', '.join(step.depends_on)})" if step.depends_on else ""
            lines.append(f"{i}. {icon} **{step.name}**{dep_text}")
            if step.description:
                lines.append(f"   {step.description}")
            if step.output and step.status == StepStatus.COMPLETED:
                lines.append(f"   → {step.output[:200]}")
            if step.error:
                lines.append(f"   ⚠️ {step.error[:200]}")

        return "\n".join(lines)

    def _progress_bar(self) -> str:
        if not self.steps:
            return "0%"
        completed = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        pct = int(completed / len(self.steps) * 100)
        return f"{completed}/{len(self.steps)} ({pct}%)"


# ── Tipos de ejecución ───────────────────────────────────────

# Ejecutor de pasos: recibe paso, retorna (éxito, output)
StepExecutor = Callable[[PlanStep], Awaitable[tuple]]
# Generador de planes: recibe goal+context, retorna lista de pasos
PlanGenerator = Callable[[str, str], Awaitable[List[Dict[str, Any]]]]
# Verificador: recibe paso+output, retorna (verificado, razón)
StepVerifier = Callable[[PlanStep, str], Awaitable[tuple]]


# ── PlanningEngine ───────────────────────────────────────────


class PlanningEngine:
    """Motor de planificación con ciclo plan → execute → verify.

    Uso:
        engine = PlanningEngine(
            plan_generator=my_llm_planner,
            step_executor=my_tool_executor,
        )
        plan = await engine.create_plan("Implementar feature X")
        result = await engine.execute(plan)
    """

    def __init__(
        self,
        *,
        plan_generator: Optional[PlanGenerator] = None,
        step_executor: Optional[StepExecutor] = None,
        step_verifier: Optional[StepVerifier] = None,
        llm_func: Optional[Callable[[str], Awaitable[str]]] = None,
        max_concurrent_steps: int = 1,
    ) -> None:
        self._plan_generator = plan_generator
        self._step_executor = step_executor
        self._step_verifier = step_verifier
        self._llm = llm_func
        self._max_concurrent = max_concurrent_steps
        self._active_plans: Dict[str, Plan] = {}

    # ── Plan creation ──────────────────────────────────────

    async def create_plan(
        self,
        goal: str,
        *,
        context: str = "",
        steps: Optional[List[Dict[str, Any]]] = None,
    ) -> Plan:
        """Crea un plan para un objetivo.

        Si se proporcionan steps, los usa directamente.
        Si no, usa el plan_generator (LLM) para generarlos.
        """
        plan = Plan(goal=goal, context=context)

        if steps:
            # Pasos proporcionados manualmente
            for s in steps[:MAX_PLAN_STEPS]:
                plan.steps.append(PlanStep(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    action=s.get("action", ""),
                    action_args=s.get("action_args", {}),
                    depends_on=s.get("depends_on", []),
                    verification=s.get("verification", ""),
                ))
        elif self._plan_generator:
            # Generar con LLM
            generated = await self._plan_generator(goal, context)
            for s in generated[:MAX_PLAN_STEPS]:
                plan.steps.append(PlanStep(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    action=s.get("action", ""),
                    action_args=s.get("action_args", {}),
                    depends_on=s.get("depends_on", []),
                    verification=s.get("verification", ""),
                ))
        elif self._llm:
            # Fallback: generar con LLM directo
            plan.steps = await self._generate_steps_with_llm(goal, context)

        self._active_plans[plan.id] = plan
        logger.info("Plan creado: id=%s goal='%s' steps=%d", plan.id, goal[:60], len(plan.steps))
        return plan

    async def _generate_steps_with_llm(
        self,
        goal: str,
        context: str,
    ) -> List[PlanStep]:
        """Genera pasos usando LLM directo."""
        if not self._llm:
            return []

        prompt = (
            f"Descompón este objetivo en pasos ejecutables:\n"
            f"Objetivo: {goal}\n"
            f"Contexto: {context}\n\n"
            "Genera un JSON array de pasos, cada uno con:\n"
            '- "name": nombre corto del paso\n'
            '- "description": qué hacer exactamente\n'
            '- "action": tipo de acción (shell, code, tool, manual)\n'
            '- "verification": cómo verificar que se completó\n'
            '- "depends_on": lista de nombres de pasos previos requeridos\n'
            f"\nMáximo {MAX_PLAN_STEPS} pasos. Responde SOLO el JSON array."
        )

        try:
            response = await self._llm(prompt)
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                raw_steps = json.loads(response[start:end])
                steps: List[PlanStep] = []
                name_to_id: Dict[str, str] = {}

                for s in raw_steps[:MAX_PLAN_STEPS]:
                    step = PlanStep(
                        name=s.get("name", ""),
                        description=s.get("description", ""),
                        action=s.get("action", ""),
                        verification=s.get("verification", ""),
                    )
                    name_to_id[step.name] = step.id
                    steps.append(step)

                # Resolver dependencias por nombre → id
                for s in raw_steps[:MAX_PLAN_STEPS]:
                    step_name = s.get("name", "")
                    if step_name in name_to_id:
                        step_id = name_to_id[step_name]
                        for step in steps:
                            if step.id == step_id:
                                step.depends_on = [
                                    name_to_id[dep]
                                    for dep in s.get("depends_on", [])
                                    if dep in name_to_id
                                ]
                                break

                return steps
        except Exception as exc:
            logger.error("Error generando pasos con LLM: %s", exc)

        return []

    # ── Execution ──────────────────────────────────────────

    async def execute(
        self,
        plan: Plan,
        *,
        on_step_complete: Optional[Callable[[PlanStep], Awaitable[None]]] = None,
    ) -> Plan:
        """Ejecuta un plan paso a paso.

        Args:
            plan: Plan a ejecutar.
            on_step_complete: Callback después de cada paso.

        Returns:
            Plan actualizado con resultados.
        """
        plan.status = PlanStatus.EXECUTING
        plan.started_at = time.time()

        while not plan.is_complete():
            ready = plan.ready_steps()
            if not ready:
                # Verificar si hay bloqueo (no hay ready pero hay pending)
                if plan.pending_steps():
                    # Posible deadlock o dependencias rotas
                    logger.warning("Plan %s: pasos bloqueados sin progreso", plan.id)
                    for step in plan.pending_steps():
                        step.status = StepStatus.BLOCKED
                    break
                break

            # Ejecutar pasos ready (respetando concurrencia)
            batch = ready[:self._max_concurrent]
            tasks = [self._execute_step(step) for step in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Callbacks
            if on_step_complete:
                for step in batch:
                    if step.is_terminal:
                        try:
                            await on_step_complete(step)
                        except Exception:
                            pass

            # Verificar si necesita replanificación
            if plan.has_failures() and plan.replan_count < MAX_REPLANS:
                should_replan = await self._should_replan(plan)
                if should_replan:
                    plan = await self._replan(plan)

        # Determinar estado final
        plan.completed_at = time.time()
        plan.duration_secs = round(plan.completed_at - (plan.started_at or plan.created_at), 2)

        if all(s.status == StepStatus.COMPLETED for s in plan.steps):
            plan.status = PlanStatus.COMPLETED
        elif plan.has_failures():
            plan.status = PlanStatus.FAILED
        else:
            plan.status = PlanStatus.COMPLETED

        self._active_plans[plan.id] = plan
        logger.info(
            "Plan %s: %s en %.1fs (%s)",
            plan.id, plan.status.value, plan.duration_secs, plan._progress_bar(),
        )
        return plan

    async def _execute_step(self, step: PlanStep) -> None:
        """Ejecuta un paso individual."""
        step.status = StepStatus.IN_PROGRESS
        step.started_at = time.time()

        if not self._step_executor:
            step.status = StepStatus.FAILED
            step.error = "No hay step_executor configurado."
            return

        try:
            success, output = await asyncio.wait_for(
                self._step_executor(step),
                timeout=STEP_TIMEOUT_SECS,
            )
            step.output = str(output)[:10_000]

            if success:
                # Verificar si pasa la verificación
                if self._step_verifier and step.verification:
                    verified, reason = await self._step_verifier(step, step.output)
                    if not verified:
                        step.status = StepStatus.FAILED
                        step.error = f"Verificación fallida: {reason}"
                        return

                step.status = StepStatus.COMPLETED
            else:
                step.retries += 1
                if step.retries < MAX_RETRIES_PER_STEP:
                    step.status = StepStatus.PENDING  # Reintentar
                    step.error = f"Intento {step.retries}: {step.output[:200]}"
                else:
                    step.status = StepStatus.FAILED
                    step.error = f"Fallido después de {step.retries} intentos: {step.output[:200]}"

        except asyncio.TimeoutError:
            step.status = StepStatus.FAILED
            step.error = f"Timeout ({STEP_TIMEOUT_SECS}s)"
        except Exception as exc:
            step.status = StepStatus.FAILED
            step.error = str(exc)[:500]

        step.completed_at = time.time()
        step.duration_secs = round(step.completed_at - (step.started_at or step.completed_at), 2)

    # ── Replanning ─────────────────────────────────────────

    async def _should_replan(self, plan: Plan) -> bool:
        """Decide si el plan necesita replanificación."""
        if not self._llm:
            return False

        failed = [s for s in plan.steps if s.status == StepStatus.FAILED]
        remaining = [s for s in plan.steps if s.status == StepStatus.PENDING]

        if not remaining:
            return False

        return len(failed) <= 2  # Solo replanificar si pocos fallos

    async def _replan(self, plan: Plan) -> Plan:
        """Replanifica pasos fallidos o pendientes."""
        plan.status = PlanStatus.REPLANNING
        plan.replan_count += 1

        if not self._llm:
            plan.status = PlanStatus.EXECUTING
            return plan

        failed = [s for s in plan.steps if s.status == StepStatus.FAILED]
        completed = [s for s in plan.steps if s.status == StepStatus.COMPLETED]

        prompt = (
            f"El plan para '{plan.goal}' necesita ajustarse.\n\n"
            f"Pasos completados: {[s.name for s in completed]}\n"
            f"Pasos fallidos:\n"
        )
        for s in failed:
            prompt += f"  - {s.name}: {s.error}\n"

        prompt += (
            "\nGenera pasos alternativos para los que fallaron. "
            "JSON array con: name, description, action, verification.\n"
            "Responde SOLO el JSON array."
        )

        try:
            response = await self._llm(prompt)
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                new_steps_data = json.loads(response[start:end])
                # Reemplazar pasos fallidos
                failed_ids = {s.id for s in failed}
                plan.steps = [s for s in plan.steps if s.id not in failed_ids]

                completed_ids = {s.id for s in completed}
                for sd in new_steps_data[:5]:
                    plan.steps.append(PlanStep(
                        name=sd.get("name", ""),
                        description=sd.get("description", ""),
                        action=sd.get("action", ""),
                        verification=sd.get("verification", ""),
                        depends_on=[cid for cid in completed_ids][:1] if completed_ids else [],
                    ))
        except Exception as exc:
            logger.error("Error en replanning: %s", exc)

        plan.status = PlanStatus.EXECUTING
        return plan

    # ── Plan management ────────────────────────────────────

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        return self._active_plans.get(plan_id)

    def list_plans(self) -> List[Plan]:
        return list(self._active_plans.values())

    async def pause_plan(self, plan_id: str) -> bool:
        plan = self._active_plans.get(plan_id)
        if plan and plan.status == PlanStatus.EXECUTING:
            plan.status = PlanStatus.PAUSED
            return True
        return False

    async def resume_plan(self, plan_id: str) -> Optional[Plan]:
        plan = self._active_plans.get(plan_id)
        if plan and plan.status == PlanStatus.PAUSED:
            return await self.execute(plan)
        return None

    def status_summary(self) -> Dict[str, Any]:
        return {
            "active_plans": len(self._active_plans),
            "plans": [
                {
                    "id": p.id,
                    "goal": p.goal[:80],
                    "status": p.status.value,
                    "progress": p._progress_bar(),
                }
                for p in self._active_plans.values()
            ],
        }
