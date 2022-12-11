import torch
from torch.utils.data import DataLoader

from lightning_lite import LightningLite
from lightning_lite.strategies import FSDPStrategy
from pytorch_lightning.demos.boring_classes import RandomDataset


def _custom_auto_wrap_policy(module, recurse, nonwrapped_numel: int, min_num_params: int = int(1e8)) -> bool:
    return nonwrapped_numel >= 2


def main():
    strategy = FSDPStrategy(
        auto_wrap_policy=_custom_auto_wrap_policy,
        activation_checkpointing=[torch.nn.Linear],
        cpu_offload=True,
    )
    lite = LightningLite(accelerator="cuda", strategy=strategy, devices=2, precision=16)
    lite.launch()

    with lite.sharded_model():
        model = torch.nn.Sequential(torch.nn.Linear(32, 32), torch.nn.ReLU(), torch.nn.Linear(32, 2))

    dataloader = DataLoader(RandomDataset(32, 64))

    # model needs to be set up first in FSDP
    model = lite.setup_module(model)

    # get parameters on the wrapped model
    optimizer = torch.optim.SGD(model.parameters(), lr=0.1)

    # optimizer nees to be set up independently
    optimizer = lite.setup_optimizers(optimizer)

    dataloader = lite.setup_dataloaders(dataloader)
    model.train()

    data_iter = iter(dataloader)
    batch = next(data_iter)
    output = model(batch)
    loss = torch.nn.functional.mse_loss(output, torch.ones_like(output))
    lite.backward(loss)
    optimizer.step()
    optimizer.zero_grad()


if __name__ == "__main__":
    main()
