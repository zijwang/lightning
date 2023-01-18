# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License
import collections
import os
from copy import deepcopy
from unittest import mock
from unittest.mock import patch

import pytest
import torch
from torch import nn
from torch.utils.data import DataLoader

from pytorch_lightning import Trainer
from pytorch_lightning.accelerators.cpu import CPUAccelerator
from pytorch_lightning.accelerators.tpu import TPUAccelerator
from pytorch_lightning.demos.boring_classes import BoringModel, RandomDataset
from pytorch_lightning.plugins import PrecisionPlugin, TPUPrecisionPlugin, XLACheckpointIO
from pytorch_lightning.strategies import DDPStrategy, TPUSpawnStrategy
from pytorch_lightning.utilities import find_shared_parameters
from tests_pytorch.helpers.runif import RunIf


class WeightSharingModule(BoringModel):
    def __init__(self):
        super().__init__()
        self.layer_1 = nn.Linear(32, 10, bias=False)
        self.layer_2 = nn.Linear(10, 32, bias=False)
        self.layer_3 = nn.Linear(32, 10, bias=False)
        self.layer_3.weight = self.layer_1.weight

    def forward(self, x):
        x = self.layer_1(x)
        x = self.layer_2(x)
        x = self.layer_3(x)
        return x


@RunIf(tpu=True, standalone=True)
@mock.patch.dict(os.environ, os.environ.copy(), clear=True)
def test_resume_training_on_cpu(tmpdir):
    """Checks if training can be resumed from a saved checkpoint on CPU."""
    # Train a model on TPU
    model = BoringModel()
    trainer = Trainer(max_epochs=1, accelerator="tpu", devices=8)
    trainer.fit(model)

    model_path = trainer.checkpoint_callback.best_model_path

    # Verify saved Tensors are on CPU
    ckpt = torch.load(model_path)
    weight_tensor = list(ckpt["state_dict"].values())[0]
    assert weight_tensor.device == torch.device("cpu")

    # Verify that training is resumed on CPU
    trainer = Trainer(max_epochs=1, default_root_dir=tmpdir)
    trainer.fit(model, ckpt_path=model_path)


@RunIf(tpu=True)
@mock.patch.dict(os.environ, os.environ.copy(), clear=True)
def test_if_test_works_after_train(tmpdir):
    """Ensure that .test() works after .fit()"""
    model = BoringModel()
    trainer = Trainer(max_epochs=1, accelerator="tpu", devices=8, default_root_dir=tmpdir, fast_dev_run=True)
    trainer.fit(model)
    out = trainer.test(model)
    assert len(out) == 1


@RunIf(skip_windows=True)
def test_accelerator_cpu_when_tpu_available(tpu_available):
    assert TPUAccelerator.is_available()
    trainer = Trainer(accelerator="cpu", devices=8)
    assert isinstance(trainer.accelerator, CPUAccelerator)


@RunIf(skip_windows=True)
@pytest.mark.parametrize(["accelerator", "devices"], [("auto", 8), ("auto", "auto"), ("tpu", None)])
def test_accelerator_tpu(accelerator, devices, tpu_available):
    assert TPUAccelerator.is_available()

    trainer = Trainer(accelerator=accelerator, devices=devices)
    assert isinstance(trainer.accelerator, TPUAccelerator)
    assert isinstance(trainer.strategy, TPUSpawnStrategy)
    assert trainer.num_devices == 8


@RunIf(tpu=True)
@mock.patch.dict(os.environ, os.environ.copy(), clear=True)
def test_manual_optimization_tpus(tmpdir):
    class ManualOptimizationModel(BoringModel):

        count = 0
        called = collections.defaultdict(int)

        def __init__(self):
            super().__init__()
            self.automatic_optimization = False

        @property
        def should_update(self):
            return self.count % 2 == 0

        def on_train_batch_start(self, batch, batch_idx):
            self.called["on_train_batch_start"] += 1
            self.weight_before = self.layer.weight.clone()

        def training_step(self, batch, batch_idx):
            self.called["training_step"] += 1
            opt = self.optimizers()
            loss = self.step(batch)

            if self.should_update:
                self.manual_backward(loss)
                opt.step()
                opt.zero_grad()
            return loss

        def on_train_batch_end(self, outputs, batch, batch_idx):
            self.called["on_train_batch_end"] += 1
            after_before = self.layer.weight.clone()
            if self.should_update:
                assert not torch.equal(self.weight_before, after_before), self.count
            else:
                assert torch.equal(self.weight_before, after_before)
            assert torch.all(self.layer.weight.grad == 0)
            self.count += 1

        def on_train_start(self):
            opt = self.optimizers()
            self.opt_step_patch = patch.object(opt, "step", wraps=opt.step)
            self.opt_step_mock = self.opt_step_patch.start()

        def on_train_end(self):
            assert self.called["training_step"] == 5
            assert self.called["on_train_batch_start"] == 5
            assert self.called["on_train_batch_end"] == 5

            self.opt_step_patch.stop()
            assert self.opt_step_mock.call_count == 3

    model = ManualOptimizationModel()
    model_copy = deepcopy(model)
    model.training_step_end = None
    model.training_epoch_end = None

    trainer = Trainer(
        max_epochs=1,
        default_root_dir=tmpdir,
        limit_train_batches=5,
        limit_test_batches=0,
        limit_val_batches=0,
        accelerator="tpu",
        devices=8,
    )
    trainer.fit(model)

    for param, param_copy in zip(model.parameters(), model_copy.parameters()):
        assert not torch.equal(param.cpu().data, param_copy.data)


def test_strategy_choice_tpu_str_ddp_spawn(tpu_available):
    with pytest.raises(ValueError, match="TPUAccelerator` can only be used with a `SingleTPUStrategy`"):
        Trainer(strategy="ddp_spawn", accelerator="tpu", devices=8)


@RunIf(skip_windows=True)
def test_strategy_choice_tpu_str_tpu_spawn_debug(tpu_available):
    trainer = Trainer(strategy="tpu_spawn_debug", accelerator="tpu", devices=8)
    assert isinstance(trainer.strategy, TPUSpawnStrategy)


@RunIf(tpu=True)
def test_strategy_choice_tpu_strategy():
    trainer = Trainer(strategy=TPUSpawnStrategy(), accelerator="tpu", devices=8)
    assert isinstance(trainer.strategy, TPUSpawnStrategy)


@RunIf(tpu=True)
@mock.patch.dict(os.environ, os.environ.copy(), clear=True)
def test_auto_parameters_tying_tpus(tmpdir):

    model = WeightSharingModule()
    shared_params = find_shared_parameters(model)

    assert shared_params[0] == ["layer_1.weight", "layer_3.weight"]

    trainer = Trainer(default_root_dir=tmpdir, limit_train_batches=5, accelerator="tpu", devices=8, max_epochs=1)
    trainer.fit(model)

    assert torch.all(torch.eq(model.layer_1.weight, model.layer_3.weight))


@RunIf(tpu=True)
@mock.patch.dict(os.environ, os.environ.copy(), clear=True)
def test_auto_parameters_tying_tpus_nested_module(tmpdir):
    class SubModule(nn.Module):
        def __init__(self, layer):
            super().__init__()
            self.layer = layer

        def forward(self, x):
            return self.layer(x)

    class NestedModule(BoringModel):
        def __init__(self):
            super().__init__()
            self.layer = nn.Linear(32, 10, bias=False)
            self.net_a = SubModule(self.layer)
            self.layer_2 = nn.Linear(10, 32, bias=False)
            self.net_b = SubModule(self.layer)

        def forward(self, x):
            x = self.net_a(x)
            x = self.layer_2(x)
            x = self.net_b(x)
            return x

    model = NestedModule()

    trainer = Trainer(default_root_dir=tmpdir, limit_train_batches=5, accelerator="tpu", devices=8, max_epochs=1)
    trainer.fit(model)

    assert torch.all(torch.eq(model.net_a.layer.weight, model.net_b.layer.weight))


def test_tpu_invalid_raises(tpu_available):
    strategy = TPUSpawnStrategy(accelerator=TPUAccelerator(), precision_plugin=PrecisionPlugin())
    with pytest.raises(ValueError, match="TPUAccelerator` can only be used with a `TPUPrecisionPlugin"):
        Trainer(strategy=strategy, devices=8)

    strategy = DDPStrategy(accelerator=TPUAccelerator(), precision_plugin=TPUPrecisionPlugin())
    with pytest.raises(ValueError, match="TPUAccelerator` can only be used with a `SingleTPUStrategy`"):
        Trainer(strategy=strategy, devices=8)


def test_tpu_invalid_raises_set_precision_with_strategy(tpu_available):
    accelerator = TPUAccelerator()
    strategy = TPUSpawnStrategy(accelerator=accelerator, precision_plugin=PrecisionPlugin())
    with pytest.raises(ValueError, match="`TPUAccelerator` can only be used with a `TPUPrecisionPlugin`"):
        Trainer(strategy=strategy, devices=8)

    accelerator = TPUAccelerator()
    strategy = DDPStrategy(accelerator=accelerator, precision_plugin=TPUPrecisionPlugin())
    with pytest.raises(
        ValueError, match="The `TPUAccelerator` can only be used with a `SingleTPUStrategy` or `TPUSpawnStrategy"
    ):
        Trainer(strategy=strategy, devices=8)


@RunIf(skip_windows=True)
def test_xla_checkpoint_plugin_being_default(tpu_available):
    trainer = Trainer(accelerator="tpu", devices=8)
    assert isinstance(trainer.strategy.checkpoint_io, XLACheckpointIO)


@RunIf(tpu=True)
@patch("torch_xla.distributed.parallel_loader.MpDeviceLoader")
@patch("pytorch_lightning.strategies.tpu_spawn.TPUSpawnStrategy.root_device")
def test_mp_device_dataloader_attribute(root_device_mock, mp_loader_mock):
    dataset = RandomDataset(32, 64)
    dataloader = DataLoader(dataset)
    processed_dataloader = TPUSpawnStrategy().process_dataloader(dataloader)
    mp_loader_mock.assert_called_with(dataloader, root_device_mock)
    assert processed_dataloader.dataset == processed_dataloader._loader.dataset


def test_warning_if_tpus_not_used(tpu_available):
    with pytest.warns(UserWarning, match="TPU available but not used. Set `accelerator` and `devices`"):
        Trainer()


@RunIf(tpu=True, standalone=True)
@pytest.mark.parametrize(
    ["devices", "expected_device_ids"],
    [
        (1, [0]),
        (8, list(range(8))),
        ("8", list(range(8))),
        ([2], [2]),
        ("2,", [2]),
    ],
)
@mock.patch.dict(os.environ, os.environ.copy(), clear=True)
def test_trainer_config_device_ids(devices, expected_device_ids):
    trainer = Trainer(accelerator="tpu", devices=devices)
    assert trainer.device_ids == expected_device_ids
    assert trainer.num_devices == len(expected_device_ids)
