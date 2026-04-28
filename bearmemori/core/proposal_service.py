import logging

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
