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
from unittest.mock import Mock

from pytorch_lightning.plugins import TPUPrecisionPlugin
from tests_pytorch.helpers.runif import RunIf


@RunIf(tpu=True)
def test_optimizer_step_calls_mark_step():
    plugin = TPUPrecisionPlugin()
    optimizer = Mock()
    with mock.patch("torch_xla.core.xla_model") as xm_mock:
        plugin.optimizer_step(optimizer=optimizer, model=Mock(), optimizer_idx=0, closure=Mock())
    optimizer.step.assert_called_once()
    xm_mock.mark_step.assert_called_once()
