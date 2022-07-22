from copy import deepcopy
from typing import Any, Dict


class ReplicatedState:

    __IDENTIFIER__ = "replicated_state"

    def __init__(self, num_replicas: int, value: Any):
        self.num_replicas = num_replicas
        self._state = {}
        for r in range(1, self.num_replicas):
            self._state[r] = deepcopy(value)
        self._state[0] = value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._state})"

    def __getitem__(self, index: int):
        return self._state[index]

    def __len__(self) -> int:
        return self.num_replicas

    def to_dict(self):
        return {"type": self.__IDENTIFIER__, "num_replicas": self.num_replicas, "state": self._state}

    @classmethod
    def from_dict(cls, dict: Dict):
        raise NotImplementedError
