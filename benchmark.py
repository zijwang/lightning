import torch.cuda

from lightning_lite.accelerators.cuda import _get_all_available_cuda_gpus
import torch.multiprocessing as mp


def run(rank):
    available_gpus = _get_all_available_cuda_gpus()
    print("rank", rank, "available:", available_gpus)

    torch.cuda.set_device(available_gpus[rank])


if __name__ == "__main__":
    mp.spawn(run, nprocs=2)
