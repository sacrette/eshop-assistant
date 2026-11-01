from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(default="", description="由认证会话覆盖")
    message: str = Field(min_length=1, description="用户本轮消息")
    conversation_id: int | None = Field(
        default=None, description="续接会话时带上;为空则新建会话,由 done 帧回传新 id"
    )
