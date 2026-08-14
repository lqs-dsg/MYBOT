from typing import Dict,List
from mybot.providers.base import LLMProvider

class ProviderRegistry:
    def __init__(self)-> None:
        self._providers:Dict[str,LLMProvider] ={}

    def register(self,name:str,provider:LLMProvider)->None:
        lower_name =name.lower()
        self._providers[lower_name]=provider
    def get(self,name:str)->LLMProvider:
        lower_name=name.lower()
        if lower_name not in self._providers:
            raise KeyError(name)
        return self._providers[lower_name]
    def list_providers(self)->List[str]:
        return list(self._providers.keys())
