from mybot.config_base import Base
from pydantic import Field
class ProviderConfig(Base):
    api_key: str| None = None
    api_base: str | None = None
    model: str =""
class ProvidersConfig(Base):
    openai: ProviderConfig=Field(default_factory=ProviderConfig)
    deepseek:ProviderConfig=Field(default_factory=ProviderConfig)

class AgentDefaults(Base):
    provider: str = "auto"
    model: str = ""


class AgentsConfig(Base):
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class Config(Base):
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
