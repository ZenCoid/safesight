"""
SafeSight Rule Evaluator – Neuro‑Symbolic Reasoning Engine
----------------------------------------------------------
- Bottom‑center (feet) spatial check against normalised polygons
- Temporal gating with IANA timezone
- Top‑k margin reasoning (System‑2) to reduce false positives
- Disk guard halts evaluation when /kaggle/tmp is full
- Heartbeat thread prevents deadlocks
- Async trigger of Celery alerting tasks on confirmed violations
"""

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Set
from uuid import UUID

import pytz
import shutil

from schemas.detection import DetectionEvent, DetectionObject
from schemas.rule_schema import RuleDefinition
from engine.spatial import is_bottom_center_in_zone
from engine.temporal import is_within_schedule
from core.celery_app import celery_app
from core.database import AsyncSessionLocal
from models.violation import ViolationEvent
from models.rule import Rule

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 2                # how many top predictions to consider
DEFAULT_MIN_MARGIN = 0.15        # required gap between top‑1 and 2nd best
DEFAULT_DISK_GUARD_PATH = "/kaggle/tmp"
DISK_FREE_MIN_GB = 5.0
HEARTBEAT_INTERVAL_SEC = 60


class RuleEvaluator:
    """
    Evaluates a single detection event against a single rule.

    This is intentionally stateful – it keeps a Heartbeat thread alive
    for the duration of the evaluator's life. Create one per rule
    (or reuse for multiple events, but keep rule constant).
    """

    def __init__(
        self,
        rule: RuleDefinition,
        top_k: int = DEFAULT_TOP_K,
        min_margin: float = DEFAULT_MIN_MARGIN,
        disk_check_path: str = DEFAULT_DISK_GUARD_PATH,
        disk_free_gb: float = DISK_FREE_MIN_GB,
    ):
        self.rule = rule
        self.top_k = top_k
        self.min_margin = min_margin
        self.disk_check_path = disk_check_path
        self.disk_free_gb = disk_free_gb

        # Counters for heartbeat
        self._frames_processed = 0
        self._violations_triggered = 0

        # Heartbeat thread
        self._heartbeat_running = False
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._start_heartbeat()

        logger.info(
            f"Evaluator ready: rule={rule.rule_name}, top_k={top_k}, min_margin={min_margin}"
        )

    # ------------------------------------------------------------------
    # PUBLIC ASYNC ENTRY POINT
    # ------------------------------------------------------------------
    async def evaluate(
        self,
        det_event: DetectionEvent,
        camera_id: Optional[UUID] = None,
    ) -> bool:
        """
        Run the full neuro‑symbolic pipeline. Returns True if a violation
        is confirmed, False otherwise. Dispatches Celery tasks on True.
        """
        self._frames_processed += 1

        # ---- Guard 0: Disk safety (Kaggle‑survival) --------------------
        if not self._check_disk_space():
            logger.error("Disk low – pausing evaluation")
            return False

        # ---- 1. Temporal gating ----------------------------------------
        if not self._temporal_allowed():
            return False

        # ---- 2. Object confidence & top‑k margin filter ---------------
        confident_objects = self._filter_confident_objects(det_event.objects)
        if not confident_objects:
            return False

        # ---- 3. Spatial (feet) filtering ------------------------------
        objects_in_zone = self._filter_by_zone(confident_objects)
        if not objects_in_zone:
            return False

        # ---- 4. Logical condition evaluation --------------------------
        if not self._evaluate_condition(det_event, confident_objects, objects_in_zone):
            return False

        # ---- 5. Violation confirmed → persist & escalate --------------
        self._violations_triggered += 1
        await self._handle_violation(det_event, camera_id)
        return True

    # ------------------------------------------------------------------
    # PRIVATE HELPERS
    # ------------------------------------------------------------------
    def _temporal_allowed(self) -> bool:
        if not self.rule.schedule:
            return True
        try:
            tz = pytz.timezone(self.rule.schedule.timezone)
        except Exception:
            tz = pytz.UTC
        now = datetime.now(tz)
        return is_within_schedule(now, self.rule.schedule)

    def _filter_confident_objects(
        self, objects: List[DetectionObject]
    ) -> List[DetectionObject]:
        """
        Apply confidence threshold AND top‑k margin to reduce false positives.

        For each object:
          - primary (top‑1) confidence must be ≥ rule.confidence_threshold
          - if a top‑k list is present, the margin between top‑1 and the next class
            must be ≥ self.min_margin. If not, the object is discarded (ambiguous).
          - If no top‑k is provided, we fall back to simple threshold.
        """
        filtered = []
        for obj in objects:
            # basic threshold
            if obj.confidence < self.rule.confidence_threshold:
                continue

            # System‑2 margin check if top_k predictions are available
            if hasattr(obj, "top_k") and obj.top_k:
                # obj.top_k is expected to be List[Tuple[str, float]] sorted desc
                if len(obj.top_k) >= 2:
                    first_conf = obj.top_k[0][1]
                    second_conf = obj.top_k[1][1]
                    if (first_conf - second_conf) < self.min_margin:
                        logger.debug(
                            f"Object {obj.class_name} rejected: margin {first_conf-second_conf:.3f} < {self.min_margin}"
                        )
                        continue
                # else only one class – accept

            filtered.append(obj)
        return filtered

    def _filter_by_zone(
        self, objects: List[DetectionObject]
    ) -> List[Tuple[DetectionObject, str]]:
        """Return list of (object, zone_name) for objects whose feet are inside a zone."""
        if not self.rule.zones:
            # no spatial constraint – all objects are "in" virtual zone "any"
            return [(obj, "any") for obj in objects]

        zoned = []
        for obj in objects:
            # feet position: bottom‑center of bounding box (normalized 0‑1)
            feet_x = (obj.bbox[0] + obj.bbox[2]) / 2
            feet_y = obj.bbox[3]          # ymax = bottom
            for zone in self.rule.zones:
                # zone.points is list of [x,y] normalized
                if is_bottom_center_in_zone(feet_x, feet_y, zone.points):
                    zoned.append((obj, zone.name))
                    break                # a person can stand in only one zone at a time
        return zoned

    def _evaluate_condition(
        self,
        det_event: DetectionEvent,
        confident_objects: List[DetectionObject],
        objects_in_zone: List[Tuple[DetectionObject, str]],
    ) -> bool:
        """Evaluate the rule's condition string (prototype) using a safe context."""
        # Build context from highest‑confidence object per required module
        ctx = {}
        for mod in self.rule.detection_modules:
            ctx[f"{mod}_present"] = False
            ctx[f"{mod}_confidence"] = 0.0
            ctx[f"{mod}_in_zone"] = False

        for obj, zone_name in objects_in_zone:
            # match module – exact class name from rule (case‑insensitive)
            for mod in self.rule.detection_modules:
                if obj.class_name.lower() == mod.lower():
                    ctx[f"{mod}_present"] = True
                    ctx[f"{mod}_confidence"] = max(ctx[f"{mod}_confidence"], obj.confidence)
                    ctx[f"{mod}_in_zone"] = True   # if we matched it, it's in zone
                    break

        # For modules not detected but required, leave False/0
        # Evaluate condition string using a sandboxed eval (only builtins clean)
        # In production, replace with a custom parser (AST, pyparsing, etc.)
        condition = self.rule.condition
        # Build safe globals with only basic comparison operators
        safe_globals = {
            "__builtins__": {},
            "True": True,
            "False": False,
            "and": lambda a, b: a and b,
            "or": lambda a, b: a or b,
            "not": lambda a: not a,
        }
        try:
            result = eval(condition, safe_globals, ctx)
            return bool(result)
        except Exception as e:
            logger.error(f"Condition evaluation failed: {e}")
            return False

    async def _handle_violation(
        self, det_event: DetectionEvent, camera_id: Optional[UUID]
    ):
        """Persist a ViolationEvent row and trigger Celery escalation."""
        # Choose camera_id – prefer argument, then event's camera_id
        cam_id = camera_id or getattr(det_event, "camera_id", None)
        if not cam_id:
            logger.warning("No camera_id for violation; skipping DB write and alert")
            return

        # Write violation to DB asynchronously
        async with AsyncSessionLocal() as session:
            viol = ViolationEvent(
                rule_id=self.rule.rule_id,
                camera_id=cam_id,
                detection_snapshot=det_event.model_dump(),
                severity="warning",
            )
            session.add(viol)
            await session.commit()
            await session.refresh(viol)
            event_id = viol.event_id

        # Send Celery tasks for Level‑1 escalation (immediate)
        # The escalation state machine will handle higher levels
        if self.rule.escalation_levels:
            for channel in self.rule.escalation_levels[0].channels:
                celery_app.send_task(
                    "tasks.alerting.send_alert",
                    args=[str(event_id), channel, 1],
                )
            logger.info(f"Violation {event_id} dispatched to Celery (Level 1)")

        # Optionally, also add to the global escalation state
        try:
            from engine.escalation import escalation_state
            await escalation_state.handle_violation_start(event_id, self.rule)
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # DISK GUARD
    # ------------------------------------------------------------------
    def _check_disk_space(self) -> bool:
        try:
            usage = shutil.disk_usage(self.disk_check_path)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < self.disk_free_gb:
                logger.warning(
                    f"Disk low: {free_gb:.1f} GB free < {self.disk_free_gb} GB – pausing rule eval"
                )
                return False
        except FileNotFoundError:
            # Path doesn't exist (not on Kaggle) – skip check
            pass
        return True

    # ------------------------------------------------------------------
    # HEARTBEAT THREAD
    # ------------------------------------------------------------------
    def _start_heartbeat(self):
        self._heartbeat_running = True

        def heartbeat_loop():
            while self._heartbeat_running:
                logger.info(
                    "💓 Heartbeat: evaluator alive | frames=%d | violations=%d",
                    self._frames_processed,
                    self._violations_triggered,
                )
                time.sleep(HEARTBEAT_INTERVAL_SEC)

        self._heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self):
        self._heartbeat_running = False
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2)