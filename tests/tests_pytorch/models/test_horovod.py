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
import json
import os
import shlex
import subprocess
import sys
from unittest.mock import patch

import numpy as np
import pytest
import torch
from torch import optim, Tensor
from torchmetrics.classification.accuracy import Accuracy

import tests_pytorch.helpers.pipelines as tpipes
from pytorch_lightning import Trainer
from pytorch_lightning.accelerators import CPUAccelerator
from pytorch_lightning.demos.boring_classes import BoringModel
from pytorch_lightning.strategies.horovod import _HOROVOD_AVAILABLE
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests_pytorch.helpers.advanced_models import BasicGAN
from tests_pytorch.helpers.runif import RunIf

if _HOROVOD_AVAILABLE:
    import horovod
    import horovod.torch as hvd


@RunIf(min_cuda_gpus=1, horovod=True)
def test_nccl_is_available_on_gpu_environment():
    from tests_pytorch.helpers.runif import _HOROVOD_NCCL_AVAILABLE

    # the GPU environment should always install Horovod NCCL
    assert _HOROVOD_NCCL_AVAILABLE


# This script will run the actual test model training in parallel
TEST_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "horovod", "train_default_model.py")


def _run_horovod(trainer_options):
    """Execute the training script across multiple workers in parallel."""
    devices = trainer_options.get("devices", 1)
    # TODO: Find out why coverage breaks CI.
    # append = '-a' if '.coverage' in os.listdir(_PROJECT_ROOT) else ''
    # str(num_processes), sys.executable, '-m', 'coverage', 'run', '--source', 'pytorch_lightning', append,
    cmdline = [
        "horovodrun",
        "-np",
        str(devices),
        sys.executable,
        TEST_SCRIPT,
        "--trainer-options",
        shlex.quote(json.dumps(trainer_options)),
    ]
    if trainer_options.get("accelerator", "cpu") == "gpu":
        cmdline += ["--on-gpu"]
    if devices == 2:
        cmdline += ["--check-size"]
    exit_code = subprocess.call(" ".join(cmdline), shell=True, env=os.environ.copy())
    assert exit_code == 0


@RunIf(horovod=True, skip_windows=True)
def test_horovod_cpu(tmpdir):
    """Test Horovod running multi-process on CPU."""
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        gradient_clip_val=1.0,
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
        strategy="horovod",
    )
    _run_horovod(trainer_options)


@RunIf(horovod=True, skip_windows=True)
def test_horovod_cpu_accumulate_grad_batches(tmpdir):
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=4,
        limit_val_batches=0,
        accumulate_grad_batches=2,
        strategy="horovod",
    )
    _run_horovod(trainer_options)


@RunIf(horovod=True, skip_windows=True)
def test_horovod_cpu_clip_grad_by_value(tmpdir):
    """Test Horovod running multi-process on CPU."""
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        gradient_clip_val=1.0,
        gradient_clip_algorithm="value",
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
        strategy="horovod",
    )
    _run_horovod(trainer_options)


@RunIf(horovod=True, skip_windows=True)
def test_horovod_cpu_implicit(tmpdir):
    """Test Horovod without specifying a backend, inferring from env set by `horovodrun`."""
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        gradient_clip_val=1.0,
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
    )
    _run_horovod(trainer_options)


@pytest.mark.xfail(raises=AssertionError, reason="unhandled cuda error")
@RunIf(min_cuda_gpus=2, horovod_nccl=True, skip_windows=True)
def test_horovod_multi_gpu(tmpdir):
    """Test Horovod with multi-GPU support."""
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        gradient_clip_val=1.0,
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
        accelerator="gpu",
        devices=2,
        strategy="horovod",
    )
    _run_horovod(trainer_options)


@pytest.mark.xfail(raises=AssertionError, reason="unhandled cuda error")
@RunIf(min_cuda_gpus=2, horovod_nccl=True, skip_windows=True)
def test_horovod_multi_gpu_accumulate_grad_batches(tmpdir):
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=4,
        limit_val_batches=0,
        accumulate_grad_batches=2,
        accelerator="gpu",
        devices=2,
        strategy="horovod",
    )
    _run_horovod(trainer_options)


@pytest.mark.xfail(reason="unhandled cuda error")
@RunIf(horovod=True, skip_windows=True, min_cuda_gpus=1)
def test_horovod_raises_unsupported_accumulate_grad_batches(tmpdir):
    """Ensure MisConfigurationException for different `accumulate_grad_batches` at different epochs for Horovod
    Strategy on multi-gpus."""

    model = BoringModel()
    with pytest.deprecated_call(match=r"horovod'\)` has been deprecated in v1.9"):
        trainer = Trainer(
            default_root_dir=tmpdir,
            enable_progress_bar=False,
            accumulate_grad_batches={0: 4, 2: 2},
            accelerator="auto",
            devices=1,
            strategy="horovod",
        )
    with pytest.raises(MisconfigurationException, match="Horovod.*does not support.*accumulate_grad_batches"):
        trainer.fit(model)


@pytest.mark.xfail(raises=AssertionError, reason="unhandled cuda error")
@RunIf(min_cuda_gpus=2, horovod_nccl=True, skip_windows=True)
def test_horovod_multi_gpu_grad_by_value(tmpdir):
    """Test Horovod with multi-GPU support."""
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        gradient_clip_val=1.0,
        gradient_clip_algorithm="value",
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
        accelerator="gpu",
        devices=2,
        strategy="horovod",
    )
    _run_horovod(trainer_options)


@pytest.mark.xfail(raises=AssertionError, reason="unhandled cuda error")
@RunIf(min_cuda_gpus=2, horovod_nccl=True, skip_windows=True)
def test_horovod_amp(tmpdir):
    """Test Horovod with multi-GPU support using native amp."""
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        gradient_clip_val=1.0,
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
        accelerator="gpu",
        devices=2,
        strategy="horovod",
        precision=16,
    )
    _run_horovod(trainer_options)


@pytest.mark.xfail(raises=AssertionError, reason="unhandled cuda error")
@RunIf(min_cuda_gpus=2, horovod_nccl=True, skip_windows=True)
def test_horovod_gather(tmpdir):
    """Test Horovod with multi-GPU support using native amp."""
    trainer_options = dict(
        default_root_dir=str(tmpdir),
        gradient_clip_val=1.0,
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
        accelerator="gpu",
        devices=2,
        strategy="horovod",
    )
    _run_horovod(trainer_options)


@pytest.mark.xfail(reason="unhandled cuda error")
@RunIf(min_cuda_gpus=2, skip_windows=True, horovod=True, horovod_nccl=True)
def test_horovod_transfer_batch_to_gpu(tmpdir):
    class TestTrainingStepModel(BoringModel):
        def training_step(self, batch, *args, **kwargs):
            assert str(batch.device) != "cpu"
            return super().training_step(batch, *args, **kwargs)

        def validation_step(self, batch, *args, **kwargs):
            assert str(batch.device) != "cpu"
            return super().validation_step(batch, *args, **kwargs)

    model = TestTrainingStepModel()

    trainer_options = dict(
        default_root_dir=str(tmpdir),
        enable_progress_bar=False,
        max_epochs=1,
        limit_train_batches=0.4,
        limit_val_batches=0.2,
        accelerator="gpu",
        devices=2,
        strategy="horovod",
    )
    with pytest.deprecated_call(match=r"horovod'\)` has been deprecated in v1.9"):
        tpipes.run_model_test_without_loggers(trainer_options, model)


@RunIf(horovod=True, skip_windows=True)
def test_horovod_multi_optimizer(tmpdir):
    model = BasicGAN()

    # fit model
    with pytest.deprecated_call(match=r"horovod'\)` has been deprecated in v1.9"):
        trainer = Trainer(
            default_root_dir=str(tmpdir),
            enable_progress_bar=False,
            max_epochs=1,
            limit_train_batches=0.4,
            limit_val_batches=0.2,
            strategy="horovod",
        )
    trainer.fit(model)
    assert trainer.state.finished, f"Training failed with {trainer.state}"

    assert len(trainer.optimizers) == 2
    for i, optimizer in enumerate(trainer.optimizers):
        assert hasattr(optimizer, "synchronize"), "optimizer has not been wrapped into DistributedOptimizer"

    def get_model_params(model):
        return set(list(model.parameters()))

    def get_optimizer_params(optimizer):
        return {p for group in optimizer.param_groups for p in group.get("params", [])}

    assert get_model_params(model.generator) != get_model_params(model.discriminator)
    assert get_model_params(model.generator) == get_optimizer_params(trainer.optimizers[0])
    assert get_model_params(model.discriminator) == get_optimizer_params(trainer.optimizers[1])


@pytest.mark.skip(reason="TODO: CI agent.jobstatus=Succeeded: Permission denied")
@RunIf(horovod=True, skip_windows=True)
def test_result_reduce_horovod(tmpdir):
    """Make sure result logging works with Horovod.

    This test mirrors tests/core/test_results.py::_ddp_test_fn
    """

    def hvd_test_fn():
        path_here = os.path.abspath(os.path.dirname(__file__))
        path_root = os.path.abspath(os.path.join(path_here, "..", ".."))
        sys.path.insert(0, os.path.abspath(path_root))

        class TestModel(BoringModel):
            def training_step(self, batch, batch_idx):
                self.training_step_called = True

                tensor = torch.tensor([1.0])
                self.log("test_tensor", tensor, sync_dist=True, reduce_fx="sum", on_step=True, on_epoch=True)

                res = self._results

                # Check that `tensor` is summed across all ranks automatically
                assert (
                    res["test_tensor"].item() == hvd.size()
                ), "Result-Log does not work properly with Horovod and Tensors"

            def training_epoch_end(self, outputs) -> None:
                assert len(outputs) == 0

        model = TestModel()
        model.val_dataloader = None

        with pytest.deprecated_call(match=r"horovod'\)` has been deprecated in v1.9"):
            trainer = Trainer(
                default_root_dir=tmpdir,
                limit_train_batches=2,
                limit_val_batches=2,
                max_epochs=1,
                log_every_n_steps=1,
                enable_model_summary=False,
                logger=False,
            )

        trainer.fit(model)

    horovod.run(hvd_test_fn, np=2)


# todo: need to be fixed :]
@pytest.mark.skip(reason="TODO: CI agent.jobstatus=Succeeded: Permission denied")
@RunIf(horovod=True, skip_windows=True, num_gpus=2, sklearn=True)
def test_accuracy_metric_horovod():
    from sklearn.metrics import accuracy_score

    num_batches = 10
    batch_size = 16
    threshold = 0.5

    def sk_metric(preds, target):
        sk_preds = (preds.view(-1).numpy() >= threshold).astype(np.uint8)
        sk_target = target.view(-1).numpy()
        return accuracy_score(y_true=sk_target, y_pred=sk_preds)

    preds = torch.rand(num_batches, batch_size)
    target = torch.randint(high=2, size=(num_batches, batch_size))

    def _compute_batch():
        with pytest.deprecated_call(match=r"horovod'\)` has been deprecated in v1.9"):
            trainer = Trainer(fast_dev_run=True, strategy="horovod", logger=False)

        assert isinstance(trainer.accelerator, CPUAccelerator)
        # TODO: test that we selected the correct strategy based on horovod flags

        metric = Accuracy(
            compute_on_step=True,
            dist_sync_on_step=True,
            dist_sync_fn=trainer.strategy.all_gather,
            threshold=threshold,
        )

        for i in range(hvd.rank(), num_batches, hvd.size()):
            batch_result = metric(preds[i], target[i])
            if hvd.rank() == 0:
                dist_preds = torch.stack([preds[i + r] for r in range(hvd.size())])
                dist_target = torch.stack([target[i + r] for r in range(hvd.size())])
                sk_batch_result = sk_metric(dist_preds, dist_target)
                assert np.allclose(batch_result.numpy(), sk_batch_result)

        # check on all batches on all ranks
        result = metric.compute()
        assert isinstance(result, Tensor)

        total_preds = torch.stack([preds[i] for i in range(num_batches)])
        total_target = torch.stack([target[i] for i in range(num_batches)])
        sk_result = sk_metric(total_preds, total_target)

        assert np.allclose(result.numpy(), sk_result)

    horovod.run(_compute_batch, np=2)


@RunIf(horovod=True, skip_windows=True)
def test_horovod_multi_optimizer_with_scheduling_stepping(tmpdir):
    class TestModel(BoringModel):
        def training_step(self, batch, batch_idx, optimizer_idx):
            return super().training_step(batch, batch_idx)

        def configure_optimizers(self):
            optimizer1 = optim.Adam(self.parameters(), lr=0.1)
            optimizer2 = optim.Adam(self.parameters(), lr=0.1)
            lr_scheduler1 = optim.lr_scheduler.StepLR(optimizer1, 1, gamma=0.1)
            lr_scheduler2 = optim.lr_scheduler.StepLR(optimizer2, 1, gamma=0.1)
            return [optimizer1, optimizer2], [lr_scheduler1, lr_scheduler2]

    model = TestModel()
    model.training_epoch_end = None

    num_workers = 8
    init_lr = 0.1 * num_workers

    with patch("horovod.torch.size", return_value=8):
        with pytest.deprecated_call(match=r"horovod'\)` has been deprecated in v1.9"):
            trainer = Trainer(
                default_root_dir=tmpdir,
                max_epochs=1,
                limit_val_batches=0.5,
                limit_train_batches=0.2,
                strategy="horovod",
            )
        trainer.fit(model)

    adjusted_lr1 = [pg["lr"] for pg in trainer.optimizers[0].param_groups][0]
    adjusted_lr2 = [pg["lr"] for pg in trainer.optimizers[1].param_groups][0]

    # Called ones after end of epoch with gamma=0.1
    assert pytest.approx(init_lr * 0.1) == adjusted_lr1

    # Called every 3 steps, meaning for 1 epoch of 11 batches, it is called 3 times with gamma=0.1
    assert pytest.approx(init_lr * 0.1) == adjusted_lr2
