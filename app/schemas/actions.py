from typing import Literal

from pydantic import BaseModel, Field


class CreateTicketRequest(BaseModel):
    conversation_id: int
    description: str = Field(min_length=1)
    ticket_type: Literal["售后", "投诉", "咨询"]
    idempotency_key: str = Field(min_length=16, max_length=100)


class CreateTicketResponse(BaseModel):
    ticket_no: str
    status: str = "人工处理待办已创建"


class CreateRefundRequest(BaseModel):
    conversation_id: int
    order_id: str = Field(min_length=1)
    reason: Literal["七天无理由", "质量问题", "发错货", "不想要了", "其他"]
    idempotency_key: str = Field(min_length=16, max_length=100)


class CreateRefundResponse(BaseModel):
    ticket_no: str
    status: str = "退款申请已提交"


class ResumeRequest(BaseModel):
    conversation_id: int
    interrupt_id: str = Field(min_length=1)
    cancelled: bool = False
    order_id: str | None = Field(default=None, min_length=1)
    confirmed: bool | None = None
