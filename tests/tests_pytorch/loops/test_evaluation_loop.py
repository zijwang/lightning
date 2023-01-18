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
# limitations under the License.
from unittest import mock
from unittest.mock import call, Mock

import torch
from torch.utils.data.dataloader import DataLoader
from torch.utils.data.sampler import BatchSampler, RandomSampler

from pytorch_lightning import Trainer
from pytorch_lightning.demos.boring_classes import BoringModel, RandomDataset
from pytorch_lightning.utilities.model_helpers import is_overridden
from tests_pytorch.helpers.runif import RunIf


@mock.patch("pytorch_lightning.loops.dataloader.evaluation_loop.EvaluationLoop._on_evaluation_epoch_end")
def test_on_evaluation_epoch_end(eval_epoch_end_mock, tmpdir):
    """Tests that `on_evaluation_epoch_end` is called for `on_validation_epoch_end` and `on_test_epoch_end`
    hooks."""
    model = BoringModel()

    trainer = Trainer(
        default_root_dir=tmpdir, limit_train_batches=2, limit_val_batches=2, max_epochs=2, enable_model_summary=False
    )

    trainer.fit(model)
    # sanity + 2 epochs
    assert eval_epoch_end_mock.call_count == 3

    trainer.test()
    # sanity + 2 epochs + called once for test
    assert eval_epoch_end_mock.call_count == 4


def test_evaluation_loop_sampler_set_epoch_called(tmpdir):
    """Tests that set_epoch is called on the dataloader's sampler (if any) during training and validation."""

    def _get_dataloader():
        dataset = RandomDataset(32, 64)
        sampler = RandomSampler(dataset)
        sampler.set_epoch = Mock()
        return DataLoader(dataset, sampler=sampler)

    model = BoringModel()
    trainer = Trainer(
        default_root_dir=tmpdir,
        limit_train_batches=1,
        limit_val_batches=1,
        max_epochs=2,
        enable_model_summary=False,
        enable_checkpointing=False,
        logger=False,
    )

    train_dataloader = _get_dataloader()
    val_dataloader = _get_dataloader()
    trainer.fit(model, train_dataloaders=train_dataloader, val_dataloaders=val_dataloader)
    # One for each epoch
    assert train_dataloader.sampler.set_epoch.call_args_list == [call(0), call(1)]
    # One for each epoch + sanity check
    assert val_dataloader.sampler.set_epoch.call_args_list == [call(0), call(0), call(1)]

    val_dataloader = _get_dataloader()
    trainer.validate(model, val_dataloader)
    assert val_dataloader.sampler.set_epoch.call_args_list == [call(2)]


def test_evaluation_loop_batch_sampler_set_epoch_called(tmpdir):
    """Tests that set_epoch is called on the dataloader's batch sampler (if any) during training and validation."""

    def _get_dataloader():
        dataset = RandomDataset(32, 64)
        sampler = RandomSampler(dataset)
        batch_sampler = BatchSampler(sampler, 2, True)
        batch_sampler.set_epoch = Mock()
        return DataLoader(dataset, batch_sampler=batch_sampler)

    model = BoringModel()
    trainer = Trainer(
        default_root_dir=tmpdir,
        limit_train_batches=1,
        limit_val_batches=1,
        max_epochs=2,
        enable_model_summary=False,
        enable_checkpointing=False,
        logger=False,
    )

    train_dataloader = _get_dataloader()
    val_dataloader = _get_dataloader()
    trainer.fit(model, train_dataloaders=train_dataloader, val_dataloaders=val_dataloader)
    # One for each epoch
    assert train_dataloader.batch_sampler.set_epoch.call_args_list == [call(0), call(1)]
    # One for each epoch + sanity check
    assert val_dataloader.batch_sampler.set_epoch.call_args_list == [call(0), call(0), call(1)]

    val_dataloader = _get_dataloader()
    trainer.validate(model, val_dataloader)
    assert val_dataloader.batch_sampler.set_epoch.call_args_list == [call(2)]


@mock.patch(
    "pytorch_lightning.trainer.connectors.logger_connector.logger_connector.LoggerConnector.log_eval_end_metrics"
)
def test_log_epoch_metrics_before_on_evaluation_end(update_eval_epoch_metrics_mock, tmpdir):
    """Test that the epoch metrics are logged before the `on_evaluation_end` hook is fired."""
    order = []
    update_eval_epoch_metrics_mock.side_effect = lambda _: order.append("log_epoch_metrics")

    class LessBoringModel(BoringModel):
        def on_validation_end(self):
            order.append("on_validation_end")
            super().on_validation_end()

    trainer = Trainer(default_root_dir=tmpdir, fast_dev_run=1, enable_model_summary=False, num_sanity_val_steps=0)
    trainer.fit(LessBoringModel())

    assert order == ["log_epoch_metrics", "on_validation_end"]


@RunIf(min_cuda_gpus=1)
def test_memory_consumption_validation(tmpdir):
    """Test that the training batch is no longer in GPU memory when running validation.

    Cannot run with MPS, since there we can only measure shared memory and not dedicated, which device has how much
    memory allocated.
    """

    initial_memory = torch.cuda.memory_allocated(0)

    class BoringLargeBatchModel(BoringModel):
        @property
        def num_params(self):
            return sum(p.numel() for p in self.parameters())

        def train_dataloader(self):
            # batch target memory >= 100x boring_model size
            batch_size = self.num_params * 100 // 32 + 1
            return DataLoader(RandomDataset(32, 5000), batch_size=batch_size)

        def val_dataloader(self):
            return self.train_dataloader()

        def training_step(self, batch, batch_idx):
            # there is a batch and the boring model, but not two batches on gpu, assume 32 bit = 4 bytes
            lower = 101 * self.num_params * 4
            upper = 201 * self.num_params * 4
            current = torch.cuda.memory_allocated(0)
            assert lower < current
            assert current - initial_memory < upper
            return super().training_step(batch, batch_idx)

        def validation_step(self, batch, batch_idx):
            # there is a batch and the boring model, but not two batches on gpu, assume 32 bit = 4 bytes
            lower = 101 * self.num_params * 4
            upper = 201 * self.num_params * 4
            current = torch.cuda.memory_allocated(0)
            assert lower < current
            assert current - initial_memory < upper
            return super().validation_step(batch, batch_idx)

    torch.cuda.empty_cache()
    trainer = Trainer(
        accelerator="gpu",
        devices=1,
        default_root_dir=tmpdir,
        fast_dev_run=2,
        enable_model_summary=False,
    )
    trainer.fit(BoringLargeBatchModel())


def test_evaluation_loop_doesnt_store_outputs_if_epoch_end_not_overridden(tmpdir):
    did_assert = False

    class TestModel(BoringModel):
        def on_test_batch_end(self, outputs, *_):
            # check `test_step` returns something
            assert outputs is not None

    model = TestModel()
    model.test_epoch_end = None
    assert not is_overridden("test_epoch_end", model)

    trainer = Trainer(default_root_dir=tmpdir, fast_dev_run=3)
    loop = trainer.test_loop.epoch_loop
    original_advance = loop.advance

    def assert_on_advance_end(*args, **kwargs):
        original_advance(*args, **kwargs)
        # should be empty
        assert not loop._outputs
        # sanity check
        nonlocal did_assert
        did_assert = True

    loop.advance = assert_on_advance_end
    trainer.test(model)
    assert did_assert
