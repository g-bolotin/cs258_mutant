import torch
import torch.nn as nn

class MutantEncoder(nn.Module):
    def __init__(self, input_dim=55, hidden_dim=32, latent_dim=16):
        super(MutantEncoder, self).__init__()

        # GRU layer to capture temporal dynamics from the sliding windows
        self.gru = nn.GRU(input_size=input_dim, hidden_size=hidden_dim, batch_first=True)

        # Two Fully Connected layers to map to the latent space
        self.fc1 = nn.Linear(hidden_dim, 24)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(24, latent_dim)

    def forward(self, x):
        # x shape: (batch_size, sequence_length, input_dim)
        # If feeding a single step, sequence_length = 1
        gru_out, _ = self.gru(x)

        # Take the output of the last time step
        last_step_out = gru_out[:, -1, :]

        # Pass through FC layers
        out = self.fc1(last_step_out)
        out = self.relu(out)
        latent_vector = self.fc2(out)

        return latent_vector