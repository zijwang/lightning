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

import os
from typing import Any, Dict
from unittest import mock
from unittest.mock import Mock

import pytest
import torch
import torch.distributed

import pytorch_lightning
from lightning_fabric.plugins.environments import (
    KubeflowEnvironment,
    LightningEnvironment,
    LSFEnvironment,
    SLURMEnvironment,
    TorchElasticEnvironment,
)
from pytorch_lightning import Trainer
from pytorch_lightning.accelerators.accelerator import Accelerator
from pytorch_lightning.accelerators.cpu import CPUAccelerator
from pytorch_lightning.accelerators.cuda import CUDAAccelerator
from pytorch_lightning.accelerators.mps import MPSAccelerator
from pytorch_lightning.plugins import DoublePrecisionPlugin, LayerSync, NativeSyncBatchNorm, PrecisionPlugin
from pytorch_lightning.plugins.io import TorchCheckpointIO
from pytorch_lightning.strategies import (
    DataParallelStrategy,
    DDPFullyShardedNativeStrategy,
    DDPShardedStrategy,
    DDPSpawnShardedStrategy,
    DDPSpawnStrategy,
    DDPStrategy,
    DeepSpeedStrategy,
    SingleDeviceStrategy,
)
from pytorch_lightning.strategies.ddp_spawn import _DDP_FORK_ALIASES
from pytorch_lightning.strategies.hpu_parallel import HPUParallelStrategy
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests_pytorch.helpers.runif import RunIf


def test_accelerator_choice_cpu(tmpdir):
    trainer = Trainer(default_root_dir=tmpdir, fast_dev_run=True)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, SingleDeviceStrategy)


def test_accelerator_invalid_choice():
    with pytest.raises(ValueError, match="You selected an invalid accelerator name: `accelerator='invalid'`"):
        Trainer(accelerator="invalid")


@RunIf(skip_windows=True, standalone=True)
def test_strategy_choice_ddp_on_cpu(tmpdir):
    """Test that selecting DDPStrategy on CPU works."""
    _test_strategy_choice_ddp_and_cpu(tmpdir, ddp_strategy_class=DDPStrategy)


@RunIf(skip_windows=True)
def test_strategy_choice_ddp_spawn_on_cpu(tmpdir):
    """Test that selecting DDPSpawnStrategy on CPU works."""
    _test_strategy_choice_ddp_and_cpu(tmpdir, ddp_strategy_class=DDPSpawnStrategy)


def _test_strategy_choice_ddp_and_cpu(tmpdir, ddp_strategy_class):
    trainer = Trainer(
        default_root_dir=tmpdir,
        fast_dev_run=True,
        strategy=ddp_strategy_class(find_unused_parameters=True),
        accelerator="cpu",
        devices=2,
    )
    assert isinstance(trainer.strategy, ddp_strategy_class)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert trainer.strategy.num_processes == 2
    assert trainer.strategy.parallel_devices == [torch.device("cpu")] * 2


@mock.patch.dict(
    os.environ,
    {
        "SLURM_NTASKS": "2",
        "SLURM_NTASKS_PER_NODE": "1",
        "SLURM_JOB_NAME": "SOME_NAME",
        "SLURM_NODEID": "0",
        "LOCAL_RANK": "0",
        "SLURM_PROCID": "0",
        "SLURM_LOCALID": "0",
    },
)
def test_custom_cluster_environment_in_slurm_environment(cuda_count_0, tmpdir):
    """Test that we choose the custom cluster even when SLURM or TE flags are around."""

    class CustomCluster(LightningEnvironment):
        @property
        def main_address(self):
            return "asdf"

        @property
        def creates_processes_externally(self) -> bool:
            return True

    trainer = Trainer(
        default_root_dir=tmpdir,
        plugins=[CustomCluster()],
        fast_dev_run=True,
        accelerator="cpu",
        strategy="ddp",
        devices=2,
    )
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPStrategy)
    assert isinstance(trainer.strategy.cluster_environment, CustomCluster)


@RunIf(mps=False)
@mock.patch.dict(
    os.environ,
    {
        "SLURM_NTASKS": "2",
        "SLURM_NTASKS_PER_NODE": "1",
        "SLURM_JOB_NAME": "SOME_NAME",
        "SLURM_NODEID": "0",
        "LOCAL_RANK": "0",
        "SLURM_PROCID": "0",
        "SLURM_LOCALID": "0",
    },
)
@mock.patch("pytorch_lightning.strategies.DDPStrategy.setup_distributed", autospec=True)
def test_custom_accelerator(cuda_count_0):
    class Accel(Accelerator):
        def setup_device(self, device: torch.device) -> None:
            pass

        def get_device_stats(self, device: torch.device) -> Dict[str, Any]:
            pass

        def teardown(self) -> None:
            pass

        @staticmethod
        def parse_devices(devices):
            return devices

        @staticmethod
        def get_parallel_devices(devices):
            return [torch.device("cpu")] * devices

        @staticmethod
        def auto_device_count() -> int:
            return 1

        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def name() -> str:
            return "custom_acc_name"

    class Prec(PrecisionPlugin):
        pass

    class Strat(SingleDeviceStrategy):
        pass

    strategy = Strat(device=torch.device("cpu"), accelerator=Accel(), precision_plugin=Prec())
    trainer = Trainer(strategy=strategy, fast_dev_run=True, devices=2)
    assert isinstance(trainer.accelerator, Accel)
    assert isinstance(trainer.strategy, Strat)
    assert isinstance(trainer.precision_plugin, Prec)
    assert trainer._accelerator_connector.strategy is strategy

    class Strat(DDPStrategy):
        pass

    strategy = Strat(accelerator=Accel(), precision_plugin=Prec())
    trainer = Trainer(strategy=strategy, fast_dev_run=True, devices=2)
    assert isinstance(trainer.accelerator, Accel)
    assert isinstance(trainer.strategy, Strat)
    assert isinstance(trainer.precision_plugin, Prec)
    assert trainer._accelerator_connector.strategy is strategy


@pytest.mark.parametrize(
    "env_vars,expected_environment",
    [
        (
            {
                "SLURM_NTASKS": "2",
                "SLURM_NTASKS_PER_NODE": "1",
                "SLURM_JOB_NAME": "SOME_NAME",
                "SLURM_NODEID": "0",
                "LOCAL_RANK": "0",
                "SLURM_PROCID": "0",
                "SLURM_LOCALID": "0",
            },
            SLURMEnvironment,
        ),
        (
            {
                "LSB_JOBID": "1",
                "LSB_DJOB_RANKFILE": "SOME_RANK_FILE",
                "JSM_NAMESPACE_LOCAL_RANK": "1",
                "JSM_NAMESPACE_SIZE": "20",
                "JSM_NAMESPACE_RANK": "1",
            },
            LSFEnvironment,
        ),
    ],
)
@mock.patch("lightning_fabric.plugins.environments.lsf.LSFEnvironment._read_hosts", return_value=["node0", "node1"])
@mock.patch("lightning_fabric.plugins.environments.lsf.LSFEnvironment._get_node_rank", return_value=0)
def test_fallback_from_ddp_spawn_to_ddp_on_cluster(_, __, env_vars, expected_environment):
    with mock.patch.dict(os.environ, env_vars, clear=True):
        trainer = Trainer(strategy="ddp_spawn", accelerator="cpu", devices=2)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPStrategy)
    assert isinstance(trainer.strategy.cluster_environment, expected_environment)


@RunIf(mps=False)
def test_interactive_incompatible_backend_error(cuda_count_2, monkeypatch):
    monkeypatch.setattr(pytorch_lightning.trainer.connectors.accelerator_connector, "_IS_INTERACTIVE", True)
    with pytest.raises(MisconfigurationException, match=r"strategy='ddp'\)`.*is not compatible"):
        Trainer(strategy="ddp", accelerator="gpu", devices=2)

    with pytest.raises(MisconfigurationException, match=r"strategy='ddp_spawn'\)`.*is not compatible"):
        Trainer(strategy="ddp_spawn", accelerator="gpu", devices=2)

    with pytest.raises(
        MisconfigurationException, match=r"strategy='ddp_sharded_spawn'\)`.*is not compatible"
    ), pytest.deprecated_call(match="FairScale has been deprecated in v1.9.0"):
        Trainer(strategy="ddp_sharded_spawn", accelerator="gpu", devices=2)

    with pytest.raises(MisconfigurationException, match=r"strategy='ddp'\)`.*is not compatible"):
        # Edge case: AcceleratorConnector maps dp to ddp if accelerator != gpu
        Trainer(strategy="dp")


def test_interactive_compatible_dp_strategy_gpu(mps_count_0, cuda_count_2, monkeypatch):
    monkeypatch.setattr(pytorch_lightning.trainer.connectors.accelerator_connector, "_IS_INTERACTIVE", True)
    trainer = Trainer(strategy="dp", accelerator="gpu")
    assert trainer.strategy.launcher is None


@RunIf(skip_windows=True)
def test_interactive_compatible_strategy_tpu(tpu_available, monkeypatch):
    monkeypatch.setattr(pytorch_lightning.trainer.connectors.accelerator_connector, "_IS_INTERACTIVE", True)
    trainer = Trainer(accelerator="tpu")
    assert trainer.strategy.launcher.is_interactive_compatible


@RunIf(skip_windows=True)
def test_interactive_compatible_strategy_ddp_fork(monkeypatch):
    monkeypatch.setattr(pytorch_lightning.trainer.connectors.accelerator_connector, "_IS_INTERACTIVE", True)
    trainer = Trainer(strategy="ddp_fork", accelerator="cpu")
    assert trainer.strategy.launcher.is_interactive_compatible


@RunIf(mps=False)
@pytest.mark.parametrize(
    ["strategy", "strategy_class"],
    [
        ("ddp", DDPStrategy),
        ("ddp_spawn", DDPSpawnStrategy),
        ("ddp_sharded", DDPShardedStrategy),
        ("ddp_sharded_spawn", DDPSpawnShardedStrategy),
        pytest.param("deepspeed", DeepSpeedStrategy, marks=RunIf(deepspeed=True)),
    ],
)
@pytest.mark.parametrize("devices", [1, 2])
def test_accelerator_choice_multi_node_gpu(cuda_count_2, tmpdir, strategy, strategy_class, devices):
    if "sharded" in strategy:
        with pytest.deprecated_call(match="FairScale has been deprecated in v1.9.0"):
            trainer = Trainer(
                default_root_dir=tmpdir, num_nodes=2, accelerator="gpu", strategy=strategy, devices=devices
            )
    else:
        trainer = Trainer(default_root_dir=tmpdir, num_nodes=2, accelerator="gpu", strategy=strategy, devices=devices)
    assert isinstance(trainer.strategy, strategy_class)


def test_accelerator_cpu(cuda_count_0):
    trainer = Trainer(accelerator="cpu")
    assert isinstance(trainer.accelerator, CPUAccelerator)

    with pytest.raises(
        MisconfigurationException,
        match="CUDAAccelerator` can not run on your system since the accelerator is not available.",
    ):
        with pytest.deprecated_call(match=r"is deprecated in v1.7 and will be removed"):
            Trainer(gpus=1)

    with pytest.raises(
        MisconfigurationException,
        match="CUDAAccelerator` can not run on your system since the accelerator is not available.",
    ):
        Trainer(accelerator="cuda")

    with pytest.deprecated_call(match=r"is deprecated in v1.7 and will be removed"):
        Trainer(accelerator="cpu", gpus=1)


@pytest.mark.parametrize("device_count", (["0"], [0, "1"], ["GPU"], [["0", "1"], [0, 1]], [False]))
def test_accelererator_invalid_type_devices(cuda_count_2, device_count):
    with pytest.raises(
        MisconfigurationException, match=r"must be an int, a string, a sequence of ints or None, but you"
    ):
        _ = Trainer(accelerator="gpu", devices=device_count)


@RunIf(min_cuda_gpus=1)
def test_accelerator_gpu():
    trainer = Trainer(accelerator="gpu", devices=1)
    assert isinstance(trainer.accelerator, CUDAAccelerator)

    trainer = Trainer(accelerator="gpu")
    assert isinstance(trainer.accelerator, CUDAAccelerator)

    trainer = Trainer(accelerator="auto", devices=1)
    assert isinstance(trainer.accelerator, CUDAAccelerator)


@pytest.mark.parametrize(["devices", "strategy_class"], [(1, SingleDeviceStrategy), (5, DDPSpawnStrategy)])
def test_accelerator_cpu_with_devices(devices, strategy_class):
    trainer = Trainer(accelerator="cpu", devices=devices)
    assert trainer.num_devices == devices
    assert isinstance(trainer.strategy, strategy_class)
    assert isinstance(trainer.accelerator, CPUAccelerator)


@RunIf(min_cuda_gpus=2)
@pytest.mark.parametrize(
    ["devices", "strategy_class"], [(1, SingleDeviceStrategy), ([1], SingleDeviceStrategy), (2, DDPSpawnStrategy)]
)
def test_accelerator_gpu_with_devices(devices, strategy_class):
    trainer = Trainer(accelerator="gpu", devices=devices)
    assert trainer.num_devices == len(devices) if isinstance(devices, list) else devices
    assert isinstance(trainer.strategy, strategy_class)
    assert isinstance(trainer.accelerator, CUDAAccelerator)


@RunIf(min_cuda_gpus=1)
def test_accelerator_auto_with_devices_gpu():
    trainer = Trainer(accelerator="auto", devices=1)
    assert isinstance(trainer.accelerator, CUDAAccelerator)
    assert trainer.num_devices == 1


def test_set_devices_if_none_cpu():
    trainer = Trainer(accelerator="cpu", devices=3)
    assert trainer.num_devices == 3


def test_unsupported_strategy_types_on_cpu_and_fallback():
    with pytest.warns(UserWarning, match="is not supported on CPUs, hence setting `strategy='ddp"):
        trainer = Trainer(accelerator="cpu", strategy="dp", num_processes=2)
    assert isinstance(trainer.strategy, DDPStrategy)


def test_exception_invalid_strategy():
    with pytest.raises(MisconfigurationException, match=r"strategy='ddp_cpu'\)` is not a valid"):
        Trainer(strategy="ddp_cpu")
    with pytest.raises(MisconfigurationException, match=r"strategy='tpu_spawn'\)` is not a valid"):
        Trainer(strategy="tpu_spawn")


@pytest.mark.parametrize(
    ["strategy", "strategy_class"],
    (
        ("ddp_spawn", DDPSpawnStrategy),
        ("ddp_spawn_find_unused_parameters_false", DDPSpawnStrategy),
        ("ddp", DDPStrategy),
        ("ddp_find_unused_parameters_false", DDPStrategy),
        ("dp", DataParallelStrategy),
        ("ddp_sharded", DDPShardedStrategy),
        ("ddp_sharded_spawn", DDPSpawnShardedStrategy),
        pytest.param("deepspeed", DeepSpeedStrategy, marks=RunIf(deepspeed=True)),
    ),
)
@pytest.mark.parametrize("accelerator", ["mps", "auto", "gpu", None, MPSAccelerator()])
def test_invalid_ddp_strategy_with_mps(accelerator, strategy, strategy_class, mps_count_1, cuda_count_0):
    if "sharded" in strategy:
        with pytest.raises(ValueError, match="strategies from the DDP family are not supported"):
            Trainer(accelerator=accelerator, strategy=strategy)
    else:
        with pytest.raises(ValueError, match="strategies from the DDP family are not supported"):
            Trainer(accelerator=accelerator, strategy=strategy)

    with pytest.raises(ValueError, match="strategies from the DDP family are not supported"), pytest.deprecated_call(
        match="FairScale has been deprecated in v1.9.0"
    ):
        Trainer(accelerator="mps", strategy=strategy_class())


@pytest.mark.parametrize(
    ["strategy", "strategy_class"],
    [
        ("ddp_spawn", DDPSpawnStrategy),
        ("ddp_spawn_find_unused_parameters_false", DDPSpawnStrategy),
        ("ddp", DDPStrategy),
        ("ddp_find_unused_parameters_false", DDPStrategy),
    ],
)
def test_strategy_choice_cpu_str(strategy, strategy_class):
    trainer = Trainer(strategy=strategy, accelerator="cpu", devices=2)
    assert isinstance(trainer.strategy, strategy_class)


@pytest.mark.parametrize("strategy_class", [DDPSpawnStrategy, DDPStrategy])
def test_strategy_choice_cpu_instance(strategy_class):
    trainer = Trainer(strategy=strategy_class(), accelerator="cpu", devices=2)
    assert isinstance(trainer.strategy, strategy_class)


@RunIf(min_cuda_gpus=2)
@pytest.mark.parametrize(
    ["strategy", "strategy_class"],
    [
        ("ddp_spawn", DDPSpawnStrategy),
        ("ddp_spawn_find_unused_parameters_false", DDPSpawnStrategy),
        ("ddp", DDPStrategy),
        ("ddp_find_unused_parameters_false", DDPStrategy),
        ("dp", DataParallelStrategy),
        ("ddp_sharded", DDPShardedStrategy),
        ("ddp_sharded_spawn", DDPSpawnShardedStrategy),
        pytest.param("deepspeed", DeepSpeedStrategy, marks=RunIf(deepspeed=True)),
    ],
)
def test_strategy_choice_gpu_str(strategy, strategy_class):
    if "sharded" in strategy:
        with pytest.deprecated_call(match="FairScale has been deprecated in v1.9.0"):
            trainer = Trainer(strategy=strategy, accelerator="gpu", devices=2)
    else:
        trainer = Trainer(strategy=strategy, accelerator="gpu", devices=2)
    assert isinstance(trainer.strategy, strategy_class)


@RunIf(min_cuda_gpus=2)
@pytest.mark.parametrize("strategy_class", [DDPSpawnStrategy, DDPStrategy])
def test_strategy_choice_gpu_instance(strategy_class):
    trainer = Trainer(strategy=strategy_class(), accelerator="gpu", devices=2)
    assert isinstance(trainer.strategy, strategy_class)


@RunIf(min_cuda_gpus=2)
@pytest.mark.parametrize("strategy_class", [DDPSpawnStrategy, DDPStrategy])
def test_device_type_when_strategy_instance_gpu_passed(strategy_class):

    trainer = Trainer(strategy=strategy_class(), accelerator="gpu", devices=2)
    assert isinstance(trainer.strategy, strategy_class)
    assert isinstance(trainer.accelerator, CUDAAccelerator)


@pytest.mark.parametrize("precision", [1, 12, "invalid"])
def test_validate_precision_type(precision):

    with pytest.raises(MisconfigurationException, match=f"Precision {repr(precision)} is invalid"):
        Trainer(precision=precision)


def test_strategy_choice_ddp_spawn_cpu():
    trainer = Trainer(strategy="ddp_spawn", accelerator="cpu", devices=2)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPSpawnStrategy)
    assert isinstance(trainer.strategy.cluster_environment, LightningEnvironment)
    assert trainer.strategy.launcher._start_method == "spawn"


@RunIf(skip_windows=True)
@mock.patch("pytorch_lightning.trainer.connectors.accelerator_connector._IS_INTERACTIVE", True)
def test_strategy_choice_ddp_fork_in_interactive():
    """Test that when accelerator and strategy are unspecified, the connector chooses DDP Fork in interactive
    environments by default."""
    trainer = Trainer(devices=2)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPSpawnStrategy)
    assert isinstance(trainer.strategy.cluster_environment, LightningEnvironment)
    assert trainer.strategy.launcher._start_method == "fork"


@RunIf(skip_windows=True)
def test_strategy_choice_ddp_fork_cpu():
    trainer = Trainer(strategy="ddp_fork", accelerator="cpu", devices=2)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPSpawnStrategy)
    assert isinstance(trainer.strategy.cluster_environment, LightningEnvironment)
    assert trainer.strategy.launcher._start_method == "fork"


@pytest.mark.parametrize("strategy,expected_cls", [("ddp", DDPStrategy), ("ddp_spawn", DDPSpawnStrategy)])
def test_strategy_choice_ddp_cuda(strategy, expected_cls, mps_count_0, cuda_count_2):
    trainer = Trainer(fast_dev_run=True, strategy=strategy, accelerator="gpu", devices=1)
    assert isinstance(trainer.accelerator, CUDAAccelerator)
    assert isinstance(trainer.strategy, expected_cls)
    assert isinstance(trainer.strategy.cluster_environment, LightningEnvironment)


@pytest.mark.parametrize("job_name,expected_env", [("some_name", SLURMEnvironment), ("bash", LightningEnvironment)])
@pytest.mark.parametrize("strategy", ["ddp", DDPStrategy])
def test_strategy_choice_ddp_slurm(cuda_count_2, strategy, job_name, expected_env):
    if not isinstance(strategy, str):
        strategy = strategy()

    with mock.patch.dict(
        os.environ,
        {
            "CUDA_VISIBLE_DEVICES": "0,1",
            "SLURM_NTASKS": "2",
            "SLURM_NTASKS_PER_NODE": "1",
            "SLURM_JOB_NAME": job_name,
            "SLURM_NODEID": "0",
            "SLURM_PROCID": "1",
            "SLURM_LOCALID": "1",
        },
    ):
        trainer = Trainer(fast_dev_run=True, strategy=strategy, accelerator="cuda", devices=2)
        assert isinstance(trainer.accelerator, CUDAAccelerator)
        assert isinstance(trainer.strategy, DDPStrategy)
        assert isinstance(trainer.strategy.cluster_environment, expected_env)


@mock.patch.dict(
    os.environ,
    {
        "CUDA_VISIBLE_DEVICES": "0,1",
        "WORLD_SIZE": "2",
        "LOCAL_WORLD_SIZE": "2",
        "RANK": "1",
        "LOCAL_RANK": "1",
        "GROUP_RANK": "0",
        "TORCHELASTIC_RUN_ID": "1",
    },
)
@mock.patch("torch.cuda.set_device")
@mock.patch("pytorch_lightning.strategies.DDPStrategy.setup_distributed", autospec=True)
def test_strategy_choice_ddp_te(_, __, mps_count_0, cuda_count_2):
    trainer = Trainer(fast_dev_run=True, strategy="ddp", accelerator="gpu", devices=2)
    assert isinstance(trainer.accelerator, CUDAAccelerator)
    assert isinstance(trainer.strategy, DDPStrategy)
    assert isinstance(trainer.strategy.cluster_environment, TorchElasticEnvironment)
    assert trainer.strategy.cluster_environment.local_rank() == 1
    assert trainer.strategy.local_rank == 1


@mock.patch.dict(
    os.environ,
    {
        "WORLD_SIZE": "2",
        "LOCAL_WORLD_SIZE": "2",
        "RANK": "1",
        "LOCAL_RANK": "1",
        "GROUP_RANK": "0",
        "TORCHELASTIC_RUN_ID": "1",
    },
)
@mock.patch("pytorch_lightning.strategies.DDPStrategy.setup_distributed", autospec=True)
def test_strategy_choice_ddp_cpu_te(cuda_count_0):
    trainer = Trainer(fast_dev_run=True, strategy="ddp_spawn", accelerator="cpu", devices=2)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPStrategy)
    assert isinstance(trainer.strategy.cluster_environment, TorchElasticEnvironment)
    assert trainer.strategy.cluster_environment.local_rank() == 1
    assert trainer.strategy.local_rank == 1


@mock.patch.dict(
    os.environ,
    {
        "CUDA_VISIBLE_DEVICES": "0",
        "KUBERNETES_PORT": "tcp://127.0.0.1:443",
        "MASTER_ADDR": "1.2.3.4",
        "MASTER_PORT": "500",
        "WORLD_SIZE": "20",
        "RANK": "1",
    },
)
@mock.patch("torch.cuda.set_device")
@mock.patch("pytorch_lightning.strategies.DDPStrategy.setup_distributed", autospec=True)
def test_strategy_choice_ddp_kubeflow(_, __, mps_count_0, cuda_count_1):
    trainer = Trainer(fast_dev_run=True, strategy="ddp", accelerator="gpu", devices=1)
    assert isinstance(trainer.accelerator, CUDAAccelerator)
    assert isinstance(trainer.strategy, DDPStrategy)
    assert isinstance(trainer.strategy.cluster_environment, KubeflowEnvironment)
    assert trainer.strategy.cluster_environment.local_rank() == 0
    assert trainer.strategy.local_rank == 0


@mock.patch.dict(
    os.environ,
    {
        "KUBERNETES_PORT": "tcp://127.0.0.1:443",
        "MASTER_ADDR": "1.2.3.4",
        "MASTER_PORT": "500",
        "WORLD_SIZE": "20",
        "RANK": "1",
    },
)
@mock.patch("pytorch_lightning.strategies.DDPStrategy.setup_distributed", autospec=True)
def test_strategy_choice_ddp_cpu_kubeflow(cuda_count_0):
    trainer = Trainer(fast_dev_run=True, strategy="ddp_spawn", accelerator="cpu", devices=2)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPStrategy)
    assert isinstance(trainer.strategy.cluster_environment, KubeflowEnvironment)
    assert trainer.strategy.cluster_environment.local_rank() == 0
    assert trainer.strategy.local_rank == 0


@mock.patch.dict(
    os.environ,
    {
        "SLURM_NTASKS": "2",
        "SLURM_NTASKS_PER_NODE": "1",
        "SLURM_JOB_NAME": "SOME_NAME",
        "SLURM_NODEID": "0",
        "LOCAL_RANK": "0",
        "SLURM_PROCID": "0",
        "SLURM_LOCALID": "0",
    },
)
@mock.patch("pytorch_lightning.strategies.DDPStrategy.setup_distributed", autospec=True)
@pytest.mark.parametrize("strategy", ["ddp", DDPStrategy()])
def test_strategy_choice_ddp_cpu_slurm(cuda_count_0, strategy):
    trainer = Trainer(fast_dev_run=True, strategy=strategy, accelerator="cpu", devices=2)
    assert isinstance(trainer.accelerator, CPUAccelerator)
    assert isinstance(trainer.strategy, DDPStrategy)
    assert isinstance(trainer.strategy.cluster_environment, SLURMEnvironment)
    assert trainer.strategy.local_rank == 0


@RunIf(min_torch="1.12")
def test_check_native_fsdp_strategy_and_fallback():
    with pytest.raises(
        MisconfigurationException,
        match=f"You selected strategy to be `{DDPFullyShardedNativeStrategy.strategy_name}`, "
        "but GPU accelerator is not used.",
    ):
        Trainer(accelerator="cpu", strategy="fsdp_native")


def test_unsupported_tpu_choice(tpu_available):
    with pytest.raises(MisconfigurationException, match=r"accelerator='tpu', precision=64\)` is not implemented"):
        Trainer(accelerator="tpu", precision=64)

    # if user didn't set strategy, AcceleratorConnector will choose the TPUSingleStrategy or TPUSpawnStrategy
    with pytest.raises(ValueError, match="TPUAccelerator` can only be used with a `SingleTPUStrategy`"), pytest.warns(
        UserWarning, match=r"accelerator='tpu', precision=16\)` but native AMP is not supported"
    ):
        Trainer(accelerator="tpu", precision=16, strategy="ddp")


@mock.patch("pytorch_lightning.accelerators.ipu.IPUAccelerator.is_available", return_value=True)
def test_unsupported_ipu_choice(mock_ipu_acc_avail, monkeypatch):
    import pytorch_lightning.strategies.ipu as ipu
    import pytorch_lightning.utilities.imports as imports

    monkeypatch.setattr(imports, "_IPU_AVAILABLE", True)
    monkeypatch.setattr(ipu, "_IPU_AVAILABLE", True)
    with pytest.raises(ValueError, match=r"accelerator='ipu', precision='bf16'\)` is not supported"):
        Trainer(accelerator="ipu", precision="bf16")
    with pytest.raises(ValueError, match=r"accelerator='ipu', precision='64'\)` is not supported"):
        Trainer(accelerator="ipu", precision=64)


@mock.patch("pytorch_lightning.accelerators.tpu._XLA_AVAILABLE", return_value=False)
@mock.patch("pytorch_lightning.utilities.imports._IPU_AVAILABLE", return_value=False)
@mock.patch("pytorch_lightning.utilities.imports._HPU_AVAILABLE", return_value=False)
def test_devices_auto_choice_cpu(cuda_count_0, *_):
    trainer = Trainer(accelerator="auto", devices="auto")
    assert trainer.num_devices == 1


@RunIf(mps=False)
def test_devices_auto_choice_gpu(cuda_count_2):
    trainer = Trainer(accelerator="auto", devices="auto")
    assert isinstance(trainer.accelerator, CUDAAccelerator)
    assert trainer.num_devices == 2


@RunIf(mps=True)
def test_devices_auto_choice_mps():
    trainer = Trainer(accelerator="auto", devices="auto")
    assert isinstance(trainer.accelerator, MPSAccelerator)
    assert trainer.num_devices == 1


@pytest.mark.parametrize(
    ["parallel_devices", "accelerator"],
    [([torch.device("cpu")], "cuda"), ([torch.device("cuda", i) for i in range(8)], "tpu")],
)
def test_parallel_devices_in_strategy_confilict_with_accelerator(parallel_devices, accelerator):
    with pytest.raises(MisconfigurationException, match=r"parallel_devices set through"):
        Trainer(strategy=DDPStrategy(parallel_devices=parallel_devices), accelerator=accelerator)


@pytest.mark.parametrize("deterministic", [True, False, pytest.param("warn", marks=RunIf(min_torch="1.11.0"))])
def test_deterministic_init(deterministic):
    trainer = Trainer(accelerator="auto", deterministic=deterministic)
    assert trainer._accelerator_connector.deterministic == deterministic
    if deterministic:
        assert os.environ.get("CUBLAS_WORKSPACE_CONFIG") == ":4096:8"
        assert os.environ.get("HOROVOD_FUSION_THRESHOLD") == "0"


@pytest.mark.parametrize(
    "sync_batchnorm,plugins,expected",
    [
        (False, [], type(None)),
        (True, [], NativeSyncBatchNorm),
        (False, [NativeSyncBatchNorm()], NativeSyncBatchNorm),
        (True, [NativeSyncBatchNorm()], NativeSyncBatchNorm),
        (False, [Mock(spec=LayerSync)], LayerSync),
    ],
)
def test_sync_batchnorm_set(sync_batchnorm, plugins, expected):
    """Test valid combinations of the sync_batchnorm Trainer flag and the plugins list of layer-sync plugins."""
    trainer = Trainer(accelerator="cpu", sync_batchnorm=sync_batchnorm, plugins=plugins, strategy="ddp")
    assert isinstance(trainer._accelerator_connector._layer_sync, expected)
    assert isinstance(trainer.strategy._layer_sync, expected)


def test_sync_batchnorm_invalid_choice(tmpdir):
    """Test that a conflicting specification of enabled sync batchnorm and a custom plugin leads to an error."""
    custom = Mock(spec=LayerSync)
    with pytest.raises(
        MisconfigurationException,
        match=r"You set `Trainer\(sync_batchnorm=True\)` and provided a `LayerSync` plugin, but this is not allowed",
    ):
        Trainer(sync_batchnorm=True, plugins=[custom])


@RunIf(skip_windows=True)
def test_sync_batchnorm_set_in_custom_strategy(tmpdir):
    """Tests if layer_sync is automatically set for custom strategy."""

    class CustomParallelStrategy(DDPStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            # Set to None so it will be overwritten by the accelerator connector.
            self._layer_sync = None

    strategy = CustomParallelStrategy()
    assert strategy._layer_sync is None
    Trainer(accelerator="cpu", strategy=strategy, sync_batchnorm=True)
    assert isinstance(strategy._layer_sync, NativeSyncBatchNorm)


@pytest.mark.parametrize(
    ["plugins", "expected"],
    [
        ([LightningEnvironment(), SLURMEnvironment()], "ClusterEnvironment"),
        ([TorchCheckpointIO(), TorchCheckpointIO()], "CheckpointIO"),
        (
            [PrecisionPlugin(), DoublePrecisionPlugin(), LightningEnvironment(), SLURMEnvironment()],
            "PrecisionPlugin, ClusterEnvironment",
        ),
    ],
)
def test_plugin_only_one_instance_for_one_type(plugins, expected):
    with pytest.raises(MisconfigurationException, match=f"Received multiple values for {expected}"):
        Trainer(plugins=plugins)


@pytest.mark.parametrize("accelerator", ("cpu", "cuda", "mps", "tpu", "ipu"))
@pytest.mark.parametrize("devices", ("0", 0, []))
def test_passing_zero_and_empty_list_to_devices_flag(accelerator, devices):
    with pytest.raises(MisconfigurationException, match="value is not a valid input using"):
        Trainer(accelerator=accelerator, devices=devices)


@pytest.mark.parametrize(
    "expected_accelerator_flag,expected_accelerator_class",
    [
        pytest.param("cuda", CUDAAccelerator, marks=RunIf(min_cuda_gpus=1)),
        pytest.param("mps", MPSAccelerator, marks=RunIf(mps=True)),
    ],
)
def test_gpu_accelerator_backend_choice(expected_accelerator_flag, expected_accelerator_class):
    trainer = Trainer(accelerator="gpu")
    assert trainer._accelerator_connector._accelerator_flag == expected_accelerator_flag
    assert isinstance(trainer.accelerator, expected_accelerator_class)


@RunIf(mps=False)
def test_gpu_accelerator_backend_choice_cuda(cuda_count_1):
    trainer = Trainer(accelerator="gpu")
    assert trainer._accelerator_connector._accelerator_flag == "cuda"
    assert isinstance(trainer.accelerator, CUDAAccelerator)


def test_gpu_accelerator_backend_choice_mps(mps_count_1):
    trainer = Trainer(accelerator="gpu")
    assert trainer._accelerator_connector._accelerator_flag == "mps"
    assert isinstance(trainer.accelerator, MPSAccelerator)


@mock.patch("pytorch_lightning.accelerators.mps.MPSAccelerator.is_available", return_value=False)
@mock.patch("pytorch_lightning.accelerators.cuda.CUDAAccelerator.is_available", return_value=False)
def test_gpu_accelerator_misconfiguration_exception(*_):
    with pytest.raises(MisconfigurationException, match="No supported gpu backend found!"):
        Trainer(accelerator="gpu")


@mock.patch("pytorch_lightning.accelerators.hpu.HPUAccelerator.is_available", return_value=True)
@mock.patch("pytorch_lightning.strategies.hpu_parallel._HPU_AVAILABLE", return_value=True)
@mock.patch("pytorch_lightning.plugins.precision.hpu._HPU_AVAILABLE", return_value=True)
def test_accelerator_specific_checkpoint_io(*_):
    ckpt_plugin = TorchCheckpointIO()
    trainer = Trainer(accelerator="hpu", strategy=HPUParallelStrategy(), plugins=[ckpt_plugin])
    assert trainer.strategy.checkpoint_io is ckpt_plugin


@pytest.mark.parametrize("strategy", _DDP_FORK_ALIASES)
@mock.patch(
    "pytorch_lightning.trainer.connectors.accelerator_connector.torch.multiprocessing.get_all_start_methods",
    return_value=[],
)
def test_ddp_fork_on_unsupported_platform(_, strategy):
    with pytest.raises(ValueError, match="process forking is not supported on this platform"):
        Trainer(accelerator="cpu", strategy=strategy)


@pytest.mark.parametrize(
    ["strategy", "strategy_cls"], [("DDP", DDPStrategy), ("DDP_FIND_UNUSED_PARAMETERS_FALSE", DDPStrategy)]
)
def test_strategy_str_passed_being_case_insensitive(strategy, strategy_cls):
    trainer = Trainer(accelerator="cpu", strategy=strategy)
    assert isinstance(trainer.strategy, strategy_cls)
