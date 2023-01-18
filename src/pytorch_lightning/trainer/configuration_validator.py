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

import pytorch_lightning as pl
from lightning_fabric.utilities.warnings import PossibleUserWarning
from pytorch_lightning.accelerators.ipu import IPUAccelerator
from pytorch_lightning.strategies import DataParallelStrategy
from pytorch_lightning.trainer.states import TrainerFn
from pytorch_lightning.utilities.exceptions import MisconfigurationException
from pytorch_lightning.utilities.model_helpers import is_overridden
from pytorch_lightning.utilities.rank_zero import rank_zero_warn
from pytorch_lightning.utilities.signature_utils import is_param_in_hook_signature


def verify_loop_configurations(trainer: "pl.Trainer") -> None:
    r"""
    Checks that the model is configured correctly before the run is started.

    Args:
        trainer: Lightning Trainer. Its `lightning_module` (the model) to check the configuration.

    """
    model = trainer.lightning_module

    if trainer.state.fn is None:
        raise ValueError("Unexpected: Trainer state fn must be set before validating loop configuration.")
    if trainer.state.fn == TrainerFn.FITTING:
        __verify_train_val_loop_configuration(trainer, model)
        __verify_manual_optimization_support(trainer, model)
        __check_training_step_requires_dataloader_iter(model)
    elif trainer.state.fn == TrainerFn.VALIDATING:
        __verify_eval_loop_configuration(model, "val")
    elif trainer.state.fn == TrainerFn.TESTING:
        __verify_eval_loop_configuration(model, "test")
    elif trainer.state.fn == TrainerFn.PREDICTING:
        __verify_eval_loop_configuration(model, "predict")

    __verify_batch_transfer_support(trainer)


def __verify_train_val_loop_configuration(trainer: "pl.Trainer", model: "pl.LightningModule") -> None:
    # -----------------------------------
    # verify model has a training step
    # -----------------------------------
    has_training_step = is_overridden("training_step", model)
    if not has_training_step:
        raise MisconfigurationException(
            "No `training_step()` method defined. Lightning `Trainer` expects as minimum a"
            " `training_step()`, `train_dataloader()` and `configure_optimizers()` to be defined."
        )

    # -----------------------------------
    # verify model has optimizer
    # -----------------------------------
    has_optimizers = is_overridden("configure_optimizers", model)
    if not has_optimizers:
        raise MisconfigurationException(
            "No `configure_optimizers()` method defined. Lightning `Trainer` expects as minimum a"
            " `training_step()`, `train_dataloader()` and `configure_optimizers()` to be defined."
        )

    overridden_optimizer_step = is_overridden("optimizer_step", model)
    overridden_optimizer_zero_grad = is_overridden("optimizer_zero_grad", model)
    automatic_optimization = model.automatic_optimization
    going_to_accumulate_grad_batches = trainer.accumulation_scheduler.going_to_accumulate_grad_batches()

    has_overridden_optimization_functions = overridden_optimizer_step or overridden_optimizer_zero_grad
    if has_overridden_optimization_functions and going_to_accumulate_grad_batches and automatic_optimization:
        rank_zero_warn(
            "When using `Trainer(accumulate_grad_batches != 1)` and overriding"
            " `LightningModule.optimizer_{step,zero_grad}`, the hooks will not be called on every batch"
            " (rather, they are called on every optimization step)."
        )

    # -----------------------------------
    # verify model for val loop
    # -----------------------------------

    has_val_loader = trainer._data_connector._val_dataloader_source.is_defined()
    has_val_step = is_overridden("validation_step", model)

    if has_val_loader and not has_val_step:
        rank_zero_warn("You passed in a `val_dataloader` but have no `validation_step`. Skipping val loop.")
    if has_val_step and not has_val_loader:
        rank_zero_warn(
            "You defined a `validation_step` but have no `val_dataloader`. Skipping val loop.",
            category=PossibleUserWarning,
        )


def __verify_eval_loop_configuration(model: "pl.LightningModule", stage: str) -> None:
    step_name = "validation_step" if stage == "val" else f"{stage}_step"
    trainer_method = "validate" if stage == "val" else stage

    has_step = is_overridden(step_name, model)

    # predict_step is not required to be overridden
    if stage == "predict":
        if model.predict_step is None:
            raise MisconfigurationException("`predict_step` cannot be None to run `Trainer.predict`")
        elif not has_step and not is_overridden("forward", model):
            raise MisconfigurationException("`Trainer.predict` requires `forward` method to run.")
    else:
        # -----------------------------------
        # verify model has an eval_step
        # -----------------------------------
        if not has_step:
            raise MisconfigurationException(f"No `{step_name}()` method defined to run `Trainer.{trainer_method}`.")


def __verify_batch_transfer_support(trainer: "pl.Trainer") -> None:
    """Raise Misconfiguration exception since these hooks are not supported in DP mode."""
    batch_transfer_hooks = ("transfer_batch_to_device", "on_after_batch_transfer")
    datahook_selector = trainer._data_connector._datahook_selector
    assert datahook_selector is not None

    for hook in batch_transfer_hooks:
        # TODO: Remove this blocker once batch transfer to device is integrated in Lightning for DP mode.
        if isinstance(trainer.strategy, DataParallelStrategy) and (
            is_overridden(hook, datahook_selector.model) or is_overridden(hook, datahook_selector.datamodule)
        ):
            raise MisconfigurationException(f"Overriding `{hook}` is not supported in DP mode.")

        if isinstance(trainer.accelerator, IPUAccelerator) and (
            is_overridden(hook, datahook_selector.model) or is_overridden(hook, datahook_selector.datamodule)
        ):
            raise MisconfigurationException(f"Overriding `{hook}` is not supported with IPUs.")


def __verify_manual_optimization_support(trainer: "pl.Trainer", model: "pl.LightningModule") -> None:
    if model.automatic_optimization:
        return
    if trainer.gradient_clip_val is not None and trainer.gradient_clip_val > 0:
        raise MisconfigurationException(
            "Automatic gradient clipping is not supported for manual optimization."
            f" Remove `Trainer(gradient_clip_val={trainer.gradient_clip_val})`"
            " or switch to automatic optimization."
        )
    if trainer.accumulate_grad_batches != 1:
        raise MisconfigurationException(
            "Automatic gradient accumulation is not supported for manual optimization."
            f" Remove `Trainer(accumulate_grad_batches={trainer.accumulate_grad_batches})`"
            " or switch to automatic optimization."
        )


def __check_training_step_requires_dataloader_iter(model: "pl.LightningModule") -> None:
    """Check if the current `training_step` is requesting `dataloader_iter`."""
    if is_param_in_hook_signature(model.training_step, "dataloader_iter", explicit=True):
        for hook in ("on_train_batch_start", "on_train_batch_end"):
            if is_overridden(hook, model):
                rank_zero_warn(
                    f"The `batch_idx` argument in `{type(model).__name__}.{hook}` hook may"
                    " not match with the actual batch index when using a `dataloader_iter`"
                    " argument in your `training_step`."
                )

        if model.truncated_bptt_steps > 0:
            raise MisconfigurationException(
                "The model taking a `dataloader_iter` argument in your `training_step` "
                "is incompatible with `truncated_bptt_steps > 0`."
            )
