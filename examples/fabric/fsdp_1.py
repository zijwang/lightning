import torch
from torch.optim import Adam

from lightning_fabric import Fabric
from lightning_fabric.strategies import FSDPStrategy


def _custom_auto_wrap_policy(module, recurse, unwrapped_params: int, min_num_params: int = int(1e8)) -> bool:
    return unwrapped_params >= 2


def main():
    strategy = FSDPStrategy(auto_wrap_policy=_custom_auto_wrap_policy)
    fabric = Fabric(accelerator="cuda", devices=2, strategy=strategy)
    fabric.launch()

    model = torch.nn.Linear(10, 10)  # total params: 10 * 10 = 100
    wrapped_model = fabric.setup_module(model)

    optimizer = Adam(wrapped_model.parameters())
    optimizer = fabric.setup_optimizers(optimizer)

    output = wrapped_model(torch.rand(5, 10, device=fabric.device))
    loss = output.sum()
    fabric.backward(loss)
    optimizer.step()
    optimizer.zero_grad()

    state = {"model": wrapped_model, "optimizer": optimizer, "loss": loss.item()}
    fabric.save("lightning_logs/sharded", state)


if __name__ == "__main__":
    main()
