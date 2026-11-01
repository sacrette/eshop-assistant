"""售后单的创建、查询与状态流转。

写操作靠两层约束保证一致性：幂等键唯一索引配内容指纹，重试返回原单、换内容复用键报 409；
状态更新带 version 条件，并发下只有一个请求能改成功。读接口对无权限的单据一律回 404，
避免通过状态码泄漏「这单存在但不属于你」。
"""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.auth import now, own_conversation
from app.db import base as db
from app.db.commerce import Account, AfterSalesCase, CaseEvent, Order, Product

# 只允许这两条边，其余组合（含重复批准、驳回后完成）都按 409 处理。
TRANSITIONS = {"pending": {"approved", "rejected"}, "approved": {"completed"}}


def order_view(order: Order, product: Product) -> dict:
    return {"order_id": order.id, "product": product.name, "product_id": product.id,
            "status": order.status, "amount": order.amount_cents / 100,
            "created_at": order.created_at.isoformat(),
            "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
            "tracking_no": order.tracking_no, "logistics": order.logistics}


async def list_orders(user_id: str) -> list[dict]:
    async with db.async_session() as session:
        rows = await session.execute(select(Order, Product).join(Product).where(Order.user_id == user_id)
                                     .order_by(Order.created_at.desc()))
        return [order_view(order, product) for order, product in rows]


async def owned_order(user_id: str, order_id: str) -> dict | None:
    return next((order for order in await list_orders(user_id) if order["order_id"] == order_id), None)


def validate_eligibility(order: Order, reason: str) -> None:
    if order.status in {"待付款", "已关闭"}:
        raise HTTPException(409, "该订单状态不支持提交售后申请")
    # 七天按 delivered_at 起算，未签收的订单不设期限。
    if reason == "七天无理由" and order.delivered_at and (now() - order.delivered_at).days >= 7:
        raise HTTPException(409, "已超过七天无理由申请期限，可联系人工核实其他售后原因")


def case_view(case: AfterSalesCase) -> dict:
    return {"id": case.id, "order_id": case.order_id, "user_id": case.user_id,
            "conversation_id": case.conversation_id, "reason": case.reason,
            "description": case.description, "status": case.status, "version": case.version,
            "created_at": case.created_at.isoformat()}


async def create_case(user: Account, order_id: str, reason: str, description: str,
                      key: str, conversation_id: int | None = None) -> dict:
    if conversation_id is not None:
        await own_conversation(conversation_id, user)
    # 指纹只用来区分「同一个键配同样的内容（可安全重放）」和「同一个键换了内容（冲突）」。
    fingerprint = hashlib.sha256(json.dumps([order_id, reason, description, conversation_id],
                                            ensure_ascii=False).encode()).hexdigest()
    async with db.async_session() as session:
        existing = await session.scalar(select(AfterSalesCase).where(
            AfterSalesCase.user_id == user.id, AfterSalesCase.idempotency_key == key))
        if existing:
            if existing.fingerprint != fingerprint:
                raise HTTPException(409, "幂等键已用于其他申请，请刷新后重试")
            return case_view(existing)
        order = await session.get(Order, order_id)
        if order is None or order.user_id != user.id:
            raise HTTPException(404, "订单不存在")
        validate_eligibility(order, reason)
        case = AfterSalesCase(id="AS" + uuid4().hex[:20], user_id=user.id, order_id=order_id,
                              active_order=order_id, conversation_id=conversation_id,
                              reason=reason, description=description, status="pending",
                              idempotency_key=key, fingerprint=fingerprint, created_at=now(), version=1)
        session.add(case)
        session.add(CaseEvent(id=uuid4().hex, case_id=case.id, actor_id=user.id,
                              action="submitted", note=reason, created_at=now()))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(select(AfterSalesCase).where(
                AfterSalesCase.user_id == user.id, AfterSalesCase.idempotency_key == key))
            if existing and existing.fingerprint == fingerprint:
                return case_view(existing)
            raise HTTPException(409, "该订单已有进行中的售后申请，或请求键已被使用")
        return case_view(case)


async def list_cases(user: Account) -> list[dict]:
    async with db.async_session() as session:
        query = select(AfterSalesCase).order_by(AfterSalesCase.created_at.desc())
        if user.role != "agent":
            query = query.where(AfterSalesCase.user_id == user.id)
        return [case_view(case) for case in (await session.scalars(query)).all()]


async def case_detail(user: Account, case_id: str) -> dict:
    async with db.async_session() as session:
        case = await session.get(AfterSalesCase, case_id)
        if case is None or (user.role != "agent" and case.user_id != user.id):
            raise HTTPException(404, "售后单不存在")
        events = (await session.scalars(select(CaseEvent).where(CaseEvent.case_id == case_id)
                                       .order_by(CaseEvent.created_at, CaseEvent.id))).all()
        order = await session.get(Order, case.order_id)
        product = await session.get(Product, order.product_id)
        return case_view(case) | {"order": order_view(order, product), "events": [
            {"id": e.id, "action": e.action, "note": e.note, "actor_id": e.actor_id,
             "created_at": e.created_at.isoformat()} for e in events]}


async def transition(user: Account, case_id: str, status: str, version: int, note: str) -> dict:
    if user.role != "agent":
        raise HTTPException(403, "需要客服权限")
    async with db.async_session() as session:
        case = await session.get(AfterSalesCase, case_id)
        if case is None:
            raise HTTPException(404, "售后单不存在")
        if status not in TRANSITIONS.get(case.status, set()):
            raise HTTPException(409, "当前状态不允许此操作，请刷新售后单")
        if status == "approved":
            order = await session.get(Order, case.order_id)
            validate_eligibility(order, case.reason)
        # 条件更新把「版本没变 + 状态没变」一起写进 WHERE，两个客服同时点批准时只有一个 rowcount=1。
        result = await session.execute(update(AfterSalesCase).where(
            AfterSalesCase.id == case_id, AfterSalesCase.version == version,
            AfterSalesCase.status == case.status).values(
                status=status, version=version + 1,
                active_order=case.order_id if status == "approved" else None))
        if result.rowcount != 1:
            raise HTTPException(409, "售后单已被更新，请刷新后重试")
        session.add(CaseEvent(id=uuid4().hex, case_id=case_id, actor_id=user.id,
                              action=status, note=note, created_at=now()))
        await session.commit()
    return await case_detail(user, case_id)
