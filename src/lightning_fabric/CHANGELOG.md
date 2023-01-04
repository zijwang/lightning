# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/).


## [1.9.0] - 202Y-MM-DD

### Added


- Added `Fabric.launch()` to programmatically launch processes (e.g. in Jupyter notebook) ([#14992](https://github.com/Lightning-AI/lightning/issues/14992))


- Added the option to launch Fabric scripts from the CLI, without the need to wrap the code into the `run` method ([#14992](https://github.com/Lightning-AI/lightning/issues/14992))


- Added `Fabric.setup_module()` and `Fabric.setup_optimizers()` to support strategies that need to set up the model before an optimizer can be created ([#15185](https://github.com/Lightning-AI/lightning/pull/15185))


- Added support for Fully Sharded Data Parallel (FSDP) training in Lightning Lite ([#14967](https://github.com/Lightning-AI/lightning/issues/14967))


- Added `lightning_fabric.accelerators.find_usable_cuda_devices` utility function ([#16147](https://github.com/PyTorchLightning/pytorch-lightning/pull/16147))


- Added basic support for LightningModules ([#16048](https://github.com/Lightning-AI/lightning/issues/16048))


- Added support for managing callbacks via `Fabric(callbacks=...)` and emitting events through `Fabric.call()` ([#16074](https://github.com/Lightning-AI/lightning/issues/16074))


### Changed

- Renamed the class `LightningLite` to `Fabric` ([#15932](https://github.com/Lightning-AI/lightning/issues/15932), [#15938](https://github.com/Lightning-AI/lightning/issues/15938))


- The `Fabric.run()` method is no longer abstract ([#14992](https://github.com/Lightning-AI/lightning/issues/14992))


- The `XLAStrategy` now inherits from `ParallelStrategy` instead of `DDPSpawnStrategy` ([#15838](https://github.com/Lightning-AI/lightning/issues/15838))


- Merged the implementation of `DDPSpawnStrategy` into `DDPStrategy` and removed `DDPSpawnStrategy` ([#14952](https://github.com/Lightning-AI/lightning/issues/14952))


- The dataloader wrapper returned from `.setup_dataloaders()` now calls `.set_epoch()` on the distributed sampler if one is used ([#16101](https://github.com/Lightning-AI/lightning/issues/16101))


### Deprecated

-


### Removed

-

### Fixed

- Restored sampling parity between PyTorch and Fabric dataloaders when using the `DistributedSampler` ([#16101](https://github.com/Lightning-AI/lightning/issues/16101))


## [1.8.6] - 2022-12-21

- minor cleaning


## [1.8.5] - 2022-12-15

- minor cleaning


## [1.8.4] - 2022-12-08

### Fixed

- Fixed `shuffle=False` having no effect when using DDP/DistributedSampler ([#15931](https://github.com/Lightning-AI/lightning/issues/15931))


## [1.8.3] - 2022-11-22

### Changed

- Temporarily removed support for Hydra multi-run ([#15737](https://github.com/Lightning-AI/lightning/pull/15737))


## [1.8.2] - 2022-11-17

### Fixed

- Fixed the automatic fallback from `LightningLite(strategy="ddp_spawn", ...)` to `LightningLite(strategy="ddp", ...)` when on an LSF cluster ([#15103](https://github.com/PyTorchLightning/pytorch-lightning/issues/15103))


## [1.8.1] - 2022-11-10

### Fixed

- Fix an issue with the SLURM `srun` detection causing permission errors ([#15485](https://github.com/Lightning-AI/lightning/issues/15485))
- Fixed the import of `lightning_lite` causing a warning 'Redirects are currently not supported in Windows or MacOs' ([#15610](https://github.com/PyTorchLightning/pytorch-lightning/issues/15610))
