import logging

from bearmemori.storage.models import Actor

logger = logging.getLogger(__name__)


class ProposalNotFoundError(Exception):
    pass


class ProposalAlreadyResolvedError(Exception):
    pass


class ProposalValidationError(Exception):
    pass


class ProposalService:
    def __init__(self, db, vector_store) -> None:
        self._db = db
        self._vector_store = vector_store

    def reject(self, proposal_id: str, reason: str | None) -> dict:
        proposal = self._db.get_proposal(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(proposal_id)
        if proposal.status != "pending":
            raise ProposalAlreadyResolvedError(proposal_id)
        self._db.resolve_proposal(proposal_id, status="rejected", note=reason)
        return {"status": "rejected"}

    def approve(self, proposal_id: str, overrides: dict | None = None) -> dict:
        overrides = overrides or {}
        proposal = self._db.get_proposal(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError(proposal_id)
        if proposal.status != "pending":
            raise ProposalAlreadyResolvedError(proposal_id)

        if proposal.proposal_type == "archive":
            applied = self._approve_archive(proposal)
        elif proposal.proposal_type == "rerank":
            applied = self._approve_rerank(proposal, overrides)
        elif proposal.proposal_type == "merge":
            applied = self._approve_merge(proposal, overrides)
        else:
            raise ProposalValidationError(f"unknown proposal_type: {proposal.proposal_type}")

        note = self._build_resolution_note(proposal, overrides)
        self._db.resolve_proposal(proposal_id, status="approved", note=note)
        return {"status": "approved", "applied": applied}

    def _approve_archive(self, proposal) -> dict:
        memory_id = proposal.memory_ids[0]
        record = self._db.get(memory_id)
        if record is None or record.archived:
            return {"archived_ids": [], "updated_ids": []}
        record.archived = True
        self._db.update(record, actor=Actor.REFLECTION)
        self._vector_store.delete(memory_id)
        return {"archived_ids": [memory_id], "updated_ids": []}

    def _approve_rerank(self, proposal, overrides: dict) -> dict:
        memory_id = proposal.memory_ids[0]
        record = self._db.get(memory_id)
        if record is None:
            raise ProposalValidationError(f"memory not found: {memory_id}")
        if record.archived:
            raise ProposalValidationError(f"memory is archived: {memory_id}")

        override_imp = overrides.get("importance")
        new_importance = (
            override_imp if override_imp is not None else proposal.recommended_importance
        )
        if new_importance is None:
            raise ProposalValidationError("importance is required for rerank")
        if not (1 <= int(new_importance) <= 10):
            raise ProposalValidationError(f"importance out of range: {new_importance}")

        record.importance = int(new_importance)
        self._db.update(record, actor=Actor.REFLECTION)
        self._vector_store.update(record)
        return {"archived_ids": [], "updated_ids": [memory_id]}

    def _build_resolution_note(self, proposal, overrides: dict) -> str | None:
        notes = []
        if proposal.proposal_type == "merge":
            rec_keep = proposal.recommended_keep_id
            override_keep = overrides.get("keep_id")
            used_keep = override_keep if override_keep is not None else rec_keep
            if used_keep and used_keep != rec_keep:
                notes.append(f"keep_id override: {rec_keep} -> {used_keep}")
        if proposal.proposal_type == "rerank":
            rec_imp = proposal.recommended_importance
            override_imp = overrides.get("importance")
            used_imp = override_imp if override_imp is not None else rec_imp
            if used_imp is not None and used_imp != rec_imp:
                notes.append(f"importance override: {rec_imp} -> {used_imp}")
        return "; ".join(notes) if notes else None
