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
import re
from unittest import mock

import pytest
import torch

from pytorch_lightning import Trainer
from pytorch_lightning.tuner.auto_gpu_select import pick_multiple_gpus
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from tests_pytorch.helpers.runif import RunIf


@RunIf(min_cuda_gpus=2)
@pytest.mark.parametrize(
    ["nb", "expected_gpu_idxs", "expected_error"],
    [(0, [], MisconfigurationException), (-1, list(range(torch.cuda.device_count())), None), (1, [0], None)],
)
def test_pick_multiple_gpus(nb, expected_gpu_idxs, expected_error):
    if expected_error:
        with pytest.raises(
            expected_error,
            match=re.escape(
                "auto_select_gpus=True, gpus=0 is not a valid configuration."
                " Please select a valid number of GPU resources when using auto_select_gpus."
            ),
        ), pytest.deprecated_call(match="The function `pick_multiple_gpus` has been deprecated in v1.9.0"):
            pick_multiple_gpus(nb)
    else:
        with pytest.deprecated_call(match="The function `pick_multiple_gpus` has been deprecated in v1.9.0"):
            assert expected_gpu_idxs == pick_multiple_gpus(nb)


def test_pick_multiple_gpus_more_than_available(cuda_count_1):
    with pytest.raises(
        MisconfigurationException, match="You requested 3 GPUs but your machine only has 1 GPUs"
    ), pytest.deprecated_call(match="The function `pick_multiple_gpus` has been deprecated in v1.9.0"):
        pick_multiple_gpus(3)


@RunIf(mps=False)
@mock.patch("pytorch_lightning.trainer.connectors.accelerator_connector.pick_multiple_gpus", return_value=[1])
def test_auto_select_gpus(_, cuda_count_2):
    with pytest.deprecated_call(match="The Trainer argument `auto_select_gpus` has been deprecated in v1.9.0"):
        trainer = Trainer(auto_select_gpus=True, accelerator="gpu", devices=1)
    assert trainer.num_devices == 1
    assert trainer.device_ids == [1]
