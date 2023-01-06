from torch.utils.data import DataLoader
import pytorch_lightning as pl
from torch.utils.data import Dataset
import torch
from torch import nn
import torch.nn.functional as F


class LitAutoEncoder(pl.LightningModule):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(28 * 28, 128), nn.ReLU(), nn.Linear(128, 3))
        self.decoder = nn.Sequential(nn.Linear(3, 128), nn.ReLU(), nn.Linear(128, 28 * 28))

    def forward(self, x):
        # in lightning, forward defines the prediction/inference actions
        embedding = self.encoder(x)
        return embedding

    def training_step(self, batch, batch_idx):
        # training_step defines the train loop. It is independent of forward
        x, y = batch
        x = x.view(x.size(0), -1)
        z = self.encoder(x)
        x_hat = self.decoder(z)
        loss = F.mse_loss(x_hat, x)
        self.log("train_loss", loss)
        return loss

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=1e-3)
        return optimizer


class DummyDataset(Dataset):
    def __init__(self) -> None:
        super().__init__()

    def __getitem__(self, index: int):
        with pl.utilities.seed.isolate_rng():
            return [torch.ones(28, 28), torch.ones(28, 28)]

    def __len__(self):
        return 10

if __name__ == "__main__":
    dataset = DummyDataset()

    trainer = pl.Trainer(logger=None, accelerator='gpu')
    trainer.fit(LitAutoEncoder(), DataLoader(dataset, num_workers=2))