from pydantic import BaseModel ,ConfigDict
from pydantic.alias_generators import to_camel
class Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",        # ★ 未知字段直接报错，而不是静默忽略
                               #   （pydantic 默认是 ignore —— 配置写错层级时
                               #    会悄悄丢掉字段，然后在别处报误导性的错）
    )