import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from autoencoder import MutantAutoencoder

def train_offline_autoencoder(csv_data_path, epochs=100, batch_size=32):
    print("--- Starting Offline Autoencoder Training ---")

    # 1. Initialize the Model, Loss function, and Optimizer
    model = MutantAutoencoder(input_dim=51, hidden_dim=32, latent_dim=16)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    # 2. Load collected Mahimahi trace data
    # (Replace this with actual pandas/csv loading logic!)
    # For now, here is a dummy tensor shaped like your data: (samples, seq_len=1, features=51)
    # raw_data = pd.read_csv(csv_data_path).values
    dummy_data = torch.rand((1000, 1, 51))

    # 3. The Training Loop
    model.train()
    for epoch in range(epochs):
        epoch_loss = 0

        # Simple batching (you'd normally use a DataLoader here)
        for i in range(0, len(dummy_data), batch_size):
            batch = dummy_data[i:i+batch_size]
            optimizer.zero_grad()

            # Forward pass: Compress to 16, expand back to 51
            reconstructed_batch = model(batch)

            loss = criterion(reconstructed_batch, batch)

            # Backpropagation
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()

        if (epoch + 1) % 10 == 0:
            print(f"Epoch [{epoch+1}/{epochs}], Loss: {epoch_loss/len(dummy_data):.6f}")

    print("Training Complete")

    save_path = "mutant_autoencoder.pth"
    torch.save(model.state_dict(), save_path)
    print(f"Model successfully saved to {save_path}")

if __name__ == "__main__":
    train_offline_autoencoder("collected_traces.csv")