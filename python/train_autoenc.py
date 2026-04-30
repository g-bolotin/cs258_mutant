import torch
import torch.nn as nn
import torch.optim as optim
import pandas as pd
import numpy as np
from torch.utils.data import TensorDataset, DataLoader
from autoencoder import MutantAutoencoder

def load_and_prep_data(csv_data_path, input_dim=51):
    print(f"Loading data from {csv_data_path}...")

    df = pd.read_csv(csv_data_path)

    # Clean the data
    # Drop columns that aren't part of the network state (like step, reward, strings)
    cols_to_drop = ['step', 'action_taken', 'reward', 'current_protocol']
    features_df = df.drop(columns=[c for c in cols_to_drop if c in df.columns], errors='ignore')

    # Fill any NaNs with 0.0
    features_df = features_df.fillna(0.0)

    # Verify dimensions
    if features_df.shape[1] != input_dim:
        print(f"WARNING: Expected {input_dim} features, but found {features_df.shape[1]} in the CSV.")
        # If you have too many, truncate. If too few, you might need to pad.
        features_df = features_df.iloc[:, :input_dim]

    # Convert to PyTorch Tensors
    # Shape needs to be (num_samples, seq_len=1, features=51)
    raw_array = features_df.values.astype(np.float32)
    tensor_data = torch.tensor(raw_array).unsqueeze(1)

    print(f"Successfully loaded {tensor_data.shape[0]} samples.")
    return tensor_data

def train_offline_autoencoder(csv_data_path, epochs=100, batch_size=32):
    print("--- Starting Offline Autoencoder Training ---")

    # Initialize the Model, Loss function, and Optimizer
    input_dimension = 51
    model = MutantAutoencoder(input_dim=input_dimension, hidden_dim=32, latent_dim=16)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    # Load Real Data and Create DataLoader
    tensor_data = load_and_prep_data(csv_data_path, input_dim=input_dimension)

    # TensorDataset wraps the tensor, DataLoader handles batching/shuffling
    dataset = TensorDataset(tensor_data)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # The Training Loop
    model.train()
    for epoch in range(epochs):
        epoch_loss = 0.0

        # Iterate automatically through the shuffled batches
        for batch_tuple in dataloader:
            batch = batch_tuple[0] # Extract the tensor from the tuple

            optimizer.zero_grad()

            # Forward pass: Compress to 16, expand back to 51
            reconstructed_batch = model(batch)

            # Calculate loss against the original input
            loss = criterion(reconstructed_batch, batch.squeeze(1))

            # Backpropagation
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item() * batch.size(0) # Track total loss

        # Calculate average loss for the epoch
        avg_epoch_loss = epoch_loss / len(dataset)

        if (epoch + 1) % 10 == 0:
            print(f"Epoch [{epoch+1}/{epochs}], Loss: {avg_epoch_loss:.6f}")

    print("Training Complete")

    # Save the Weights
    save_path = "mutant_autoencoder.pth"
    torch.save(model.state_dict(), save_path)
    print(f"Model successfully saved to {save_path}")

if __name__ == "__main__":
    train_offline_autoencoder("../trcgen/master_collected_traces.csv", epochs=100, batch_size=32)