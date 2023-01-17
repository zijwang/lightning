import torch
from torch.optim import Adam
import torch.nn as nn

from lightning_fabric import Fabric
from lightning_fabric.strategies import FSDPStrategy


def _custom_auto_wrap_policy(module, recurse, unwrapped_params: int, min_num_params: int = int(1e8)) -> bool:
    return unwrapped_params >= 2


class BigModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.layer = torch.nn.Linear(10, 10)

    def forward(self, x):
        return self.layer(x)


def main():
    strategy = FSDPStrategy(auto_wrap_policy=_custom_auto_wrap_policy)
    fabric = Fabric(accelerator="cuda", devices=2, strategy=strategy)
    fabric.launch()

    # with fabric.sharded_model():
    model = BigModel()  # total params: 10 * 10 = 100
    wrapped_model = fabric.setup_module(model)

    optimizer = Adam(wrapped_model.parameters())
    optimizer = fabric.setup_optimizers(optimizer)

    output = wrapped_model(torch.rand(5, 10, device=fabric.device))
    loss = output.sum()
    fabric.backward(loss)
    optimizer.step()
    optimizer.zero_grad()

    state = {"model": wrapped_model, "optimizer": optimizer, "loss": loss.item()}
    fabric.save(state, "lightning_logs/sharded_2")

    # Loading
    model = BigModel()
    print("before", model.layer.weight.data)
    wrapped_model = fabric.setup_module(model)
    optimizer = Adam(wrapped_model.parameters())
    optimizer = fabric.setup_optimizers(optimizer)

    state = {"model": wrapped_model, "optimizer": optimizer, "loss": loss.item()}
    fabric.load("lightning_logs/sharded_2", state)
    print("after", model.layer.weight)


if __name__ == "__main__":
    main()
