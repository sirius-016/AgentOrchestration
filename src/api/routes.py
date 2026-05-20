"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}


# Dead-letter queue viewer endpoints
from src.queue import DeadLetterQueue

dlq = DeadLetterQueue()


@router.get("/dead-letter")
async def list_dead_letter_messages(queue: Optional[str] = None):
    """List dead-letter messages with redacted summaries (default view).

    Payloads are redacted by default. Use /dead-letter/{message_id}/raw
    with actor and reason to access raw data.
    """
    return {"messages": dlq.list_messages(queue=queue)}


@router.get("/dead-letter/{message_id}")
async def get_dead_letter_message(message_id: str):
    """Get a single dead-letter message with redacted payload."""
    msg = dlq.list_messages()
    for m in msg:
        if m["message_id"] == message_id:
            return m
    raise HTTPException(status_code=404, detail="Dead-letter message not found")


@router.get("/dead-letter/{message_id}/raw")
async def get_raw_dead_letter_message(message_id: str, actor: str, reason: str):
    """Get raw (unredacted) dead-letter message payload.

    This is the elevated access path. Actor and reason are required
    and all access is audit-logged.
    """
    if not actor or not reason:
        raise HTTPException(
            status_code=400,
            detail="Both 'actor' and 'reason' are required for raw data access"
        )
    msg = dlq.get_raw_message(message_id, actor=actor, reason=reason)
    if not msg:
        raise HTTPException(status_code=404, detail="Dead-letter message not found")
    return msg


@router.get("/dead-letter/audit")
async def get_dead_letter_audit_log(message_id: Optional[str] = None):
    """Retrieve audit log for raw data access to dead-letter messages."""
    return {"entries": dlq.get_audit_log(message_id=message_id)}
