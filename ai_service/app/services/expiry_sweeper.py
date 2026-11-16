"""Expiry sweeper and checkpoint pruning service for HITL workflows.

Periodically:
1. Sweeps expired PendingApproval records (expires_at <= now()).
2. Marks status as EXPIRED and records decided_at.
3. Automatically cancels pending transfer drafts at the Banking API to release account locks.
4. Resumes/closes interrupted LangGraph threads.
5. Prunes terminal/stale WorkflowCheckpointMetadata and SQLite checkpointer tables
   older than the retention threshold (default: 7 days).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AISettings, get_settings
from app.core.security import create_service_token_for_user
from app.integrations.banking_client import BankingClient
from app.models.approval import ApprovalStatus, PendingApproval, WorkflowType
from app.models.chat import ChatUserReference, Conversation
from app.models.checkpoint import WorkflowCheckpointMetadata

logger = logging.getLogger(__name__)


class ExpirySweeperService:
    """Service to sweep expired approvals and prune stale workflow checkpoints."""

    def __init__(self, db: Session, settings: AISettings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def sweep_expired_approvals(
        self,
        raw_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Identify expired approvals, cancel banking drafts, and mark them EXPIRED.

        Args:
            raw_token: Optional Bearer JWT used for banking API draft cancellation.
                       If not provided, a service token is automatically generated
                       for the user owning the approval.

        Returns:
            List of summary dicts for each swept approval.
        """
        now = datetime.now(UTC)
        stmt = (
            select(PendingApproval)
            .where(
                PendingApproval.status.in_([
                    ApprovalStatus.PENDING.value,
                    ApprovalStatus.CONFIRMED.value,
                    ApprovalStatus.AUTH_REQUIRED.value,
                ])
            )
            .where(PendingApproval.expires_at <= now)
            .order_by(PendingApproval.expires_at.asc())
        )
        expired_approvals = list(self.db.execute(stmt).scalars().all())
        if not expired_approvals:
            return []

        logger.info("Found %d expired approvals to sweep", len(expired_approvals))
        results: list[dict[str, Any]] = []

        for approval in expired_approvals:
            cancelled_draft = False

            # Cancel draft at banking service if applicable
            if (
                approval.banking_resource_id
                and approval.workflow_type == WorkflowType.TRANSFER.value
            ):
                token = raw_token
                if not token:
                    user_stmt = (
                        select(ChatUserReference.banking_user_id)
                        .join(Conversation, Conversation.user_ref_id == ChatUserReference.id)
                        .where(Conversation.id == approval.conversation_id)
                    )
                    uid = self.db.execute(user_stmt).scalar_one_or_none()
                    if uid:
                        try:
                            token = create_service_token_for_user(uid, self.settings)
                        except Exception as exc:
                            logger.debug(
                                "Failed creating service token for sweeper draft cancellation: %s",
                                exc,
                            )

                if token:
                    try:
                        client = BankingClient(settings=self.settings, access_token=token)
                        client.cancel_transfer(approval.banking_resource_id)
                        cancelled_draft = True
                        logger.info(
                            "Cancelled expired banking transfer draft %s for approval %s",
                            approval.banking_resource_id,
                            approval.id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to cancel expired banking transfer draft '%s': %s",
                            approval.banking_resource_id,
                            exc,
                        )

            approval.status = ApprovalStatus.EXPIRED.value
            approval.decided_at = now

            # Update associated checkpoint metadata
            chk = self.db.get(WorkflowCheckpointMetadata, approval.thread_id)
            if chk:
                chk.status = "EXPIRED"

            # Attempt to unstick paused LangGraph interrupts
            try:
                from app.agents.graph import resume_graph

                resume_graph(
                    thread_id=approval.thread_id,
                    resume_payload={
                        "decision": "REJECT",
                        "approval_id": approval.id,
                        "cancelled": True,
                        "expired": True,
                    },
                    access_token=raw_token or "",
                )
            except Exception as exc:
                logger.debug("Graph resume on expired approval %s: %s", approval.id, exc)

            results.append({
                "approval_id": approval.id,
                "conversation_id": approval.conversation_id,
                "workflow": approval.workflow_type,
                "banking_resource_id": approval.banking_resource_id,
                "cancelled_draft": cancelled_draft,
                "expired_at": approval.expires_at.isoformat() if approval.expires_at else None,
                "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            })

        self.db.commit()
        for approval in expired_approvals:
            self.db.refresh(approval)

        return results

    def prune_checkpoints(
        self,
        older_than_days: int = 7,
        db_path: str | None = None,
    ) -> dict[str, int]:
        """Prune old/terminal WorkflowCheckpointMetadata and SQLite checkpointer tables.

        Args:
            older_than_days: Retention threshold in days (default: 7).
            db_path: Optional explicit path to SQLite checkpointer database.

        Returns:
            Dict containing counts of pruned metadata records, checkpoints, blobs, and writes.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=older_than_days)

        # 1. Prune WorkflowCheckpointMetadata
        meta_stmt = (
            select(WorkflowCheckpointMetadata)
            .where(
                (WorkflowCheckpointMetadata.created_at <= cutoff)
                | (
                    WorkflowCheckpointMetadata.status.in_([
                        "EXPIRED",
                        "CLEANED",
                        "PRUNED",
                        "EXECUTED",
                        "REJECTED",
                        "SUPERSEDED",
                    ])
                    & (
                        (WorkflowCheckpointMetadata.expires_at <= cutoff)
                        | (WorkflowCheckpointMetadata.cleaned_at.is_not(None))
                        | (WorkflowCheckpointMetadata.created_at <= cutoff)
                    )
                )
            )
        )
        stale_metas = list(self.db.execute(meta_stmt).scalars().all())
        pruned_meta_count = len(stale_metas)
        pruned_thread_ids = [m.thread_id for m in stale_metas]

        for m in stale_metas:
            self.db.delete(m)
        self.db.commit()

        # 2. Prune SQLite tables (checkpoints, checkpoint_blobs, checkpoint_writes)
        pruned_chk = 0
        pruned_blobs = 0
        pruned_writes = 0

        target_db = db_path
        if not target_db:
            db_url = self.settings.database_url
            if db_url.startswith("sqlite:///"):
                target_db = db_url.replace("sqlite:///", "")
            elif db_url == "sqlite://":
                target_db = None

        if target_db and os.path.isfile(target_db) and pruned_thread_ids:
            try:
                import sqlite3

                conn = sqlite3.connect(target_db)
                cur = conn.cursor()
                existing_tables = {
                    r[0]
                    for r in cur.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }

                # Parameterized batches of thread IDs
                batch_size = 500
                for i in range(0, len(pruned_thread_ids), batch_size):
                    batch = pruned_thread_ids[i : i + batch_size]
                    placeholders = ",".join("?" for _ in batch)

                    if "checkpoints" in existing_tables:
                        cur.execute(
                            f"DELETE FROM checkpoints WHERE thread_id IN ({placeholders})",
                            batch,
                        )
                        pruned_chk += cur.rowcount

                    if "checkpoint_blobs" in existing_tables:
                        cur.execute(
                            f"DELETE FROM checkpoint_blobs WHERE thread_id IN ({placeholders})",
                            batch,
                        )
                        pruned_blobs += cur.rowcount

                    if "checkpoint_writes" in existing_tables:
                        cur.execute(
                            f"DELETE FROM checkpoint_writes WHERE thread_id IN ({placeholders})",
                            batch,
                        )
                        pruned_writes += cur.rowcount

                conn.commit()
                conn.close()
            except Exception as exc:
                logger.warning("Error pruning SQLite checkpointer tables: %s", exc)

        # 3. Clean up in-memory checkpointer storage if running MemorySaver
        try:
            from app.agents import graph

            cp = getattr(graph, "_checkpointer", None)
            if cp and hasattr(cp, "storage") and isinstance(cp.storage, dict):
                for tid in pruned_thread_ids:
                    cp.storage.pop(tid, None)
        except Exception as exc:
            logger.debug("In-memory checkpointer cleanup error: %s", exc)

        logger.info(
            "Pruned checkpoints older than %d days: meta=%d, chk=%d, blobs=%d, writes=%d",
            older_than_days,
            pruned_meta_count,
            pruned_chk,
            pruned_blobs,
            pruned_writes,
        )
        return {
            "pruned_metadata": pruned_meta_count,
            "pruned_checkpoints": pruned_chk,
            "pruned_blobs": pruned_blobs,
            "pruned_writes": pruned_writes,
        }

    def run_sweep_cycle(
        self,
        raw_token: str | None = None,
        older_than_days: int = 7,
        db_path: str | None = None,
    ) -> dict[str, Any]:
        """Run a full sweep cycle: sweep expired approvals and prune checkpoints."""
        swept = self.sweep_expired_approvals(raw_token=raw_token)
        pruned = self.prune_checkpoints(older_than_days=older_than_days, db_path=db_path)

        return {
            "swept_count": len(swept),
            "swept_approvals": [s["approval_id"] for s in swept],
            "swept_details": swept,
            "pruned_metadata": pruned["pruned_metadata"],
            "pruned_checkpoints": pruned["pruned_checkpoints"],
            "pruned_blobs": pruned["pruned_blobs"],
            "pruned_writes": pruned["pruned_writes"],
        }


async def run_periodic_sweeper(
    session_factory: sessionmaker[Session],
    settings: AISettings,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Async background task that runs periodic sweep cycles until stopped."""
    interval = max(5, settings.sweeper_interval_seconds)
    logger.info("Starting periodic expiry sweeper task (interval=%ds)", interval)

    while True:
        if stop_event and stop_event.is_set():
            break

        try:
            with session_factory() as db:
                sweeper = ExpirySweeperService(db, settings=settings)
                res = sweeper.run_sweep_cycle(
                    older_than_days=settings.checkpoint_retention_days
                )
                if res["swept_count"] > 0 or res["pruned_metadata"] > 0:
                    logger.info(
                        "Periodic sweeper cycle: swept=%d, pruned_meta=%d, pruned_chks=%d",
                        res["swept_count"],
                        res["pruned_metadata"],
                        res["pruned_checkpoints"],
                    )
        except Exception as exc:
            logger.exception("Error during periodic sweeper execution: %s", exc)

        try:
            if stop_event:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break
            else:
                await asyncio.sleep(interval)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            logger.info("Periodic expiry sweeper task cancelled")
            break
