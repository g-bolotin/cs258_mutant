import torch
import torch.nn as nn

class MutantAutoencoder(nn.Module):
    def __init__(self, input_dim=55, hidden_dim=32, latent_dim=16):
        super(MutantAutoencoder, self).__init__()

        # --- ENCODER ---
        self.gru = nn.GRU(input_size=input_dim, hidden_size=hidden_dim, batch_first=True)
        self.fc1 = nn.Linear(hidden_dim, 24)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(24, latent_dim)

        # --- DECODER ---
        self.dec_fc1 = nn.Linear(latent_dim, 24)
        self.dec_fc2 = nn.Linear(24, hidden_dim)
        self.dec_out = nn.Linear(hidden_dim, input_dim)

    def encode(self, x):
        gru_out, _ = self.gru(x)
        last_step = gru_out[:, -1, :]
        out = self.relu(self.fc1(last_step))
        return self.fc2(out)

    def forward(self, x):
        # Compress
        latent = self.encode(x)
        # Expand back out
        out = self.relu(self.dec_fc1(latent))
        out = self.relu(self.dec_fc2(out))
        return self.dec_out(out)
