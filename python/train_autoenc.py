import torch
import torch.nn as nn
import torch.optim as optim
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from torch.utils.data import TensorDataset, DataLoader
from autoencoder import MutantAutoencoder
import joblib
from sklearn.preprocessing import MinMaxScaler
import os

def load_and_prep_data(csv_data_path, input_dim=55):
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
    # Shape needs to be (num_samples, seq_len=1, features=55)
    raw_array = features_df.values.astype(np.float32)
    scaler = MinMaxScaler()
    scaled_array = scaler.fit_transform(raw_array)

    # Save the scaler so the RL runner can use it live
    joblib.dump(scaler, 'mutant_scaler.save')
    print("Scaler saved to mutant_scaler.save")

    X_train, X_test = train_test_split(scaled_array, test_size=0.2, random_state=42)

    print(f"Training samples: {len(X_train)} | Validation samples: {len(X_test)}")

    train_tensor = torch.tensor(X_train).unsqueeze(1)
    test_tensor = torch.tensor(X_test).unsqueeze(1)

    return train_tensor, test_tensor


def train_offline_autoencoder(csv_data_path, epochs=100, batch_size=32):
    print("--- Starting Offline Autoencoder Training ---")

    # Initialize the Model, Loss function, and Optimizer
    input_dimension = 55
    model = MutantAutoencoder(input_dim=input_dimension, hidden_dim=32, latent_dim=16)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    # Get both datasets
    train_tensor, test_tensor = load_and_prep_data(csv_data_path, input_dim=input_dimension)

    # Create two DataLoaders
    train_loader = DataLoader(TensorDataset(train_tensor), batch_size=batch_size, shuffle=True)
    test_loader = DataLoader(TensorDataset(test_tensor), batch_size=batch_size, shuffle=False)

    for epoch in range(epochs):
        # --- TRAINING PHASE ---
        model.train()
        train_loss = 0.0
        for batch_tuple in train_loader:
            batch = batch_tuple[0]
            optimizer.zero_grad()
            reconstructed = model(batch)
            loss = criterion(reconstructed, batch.squeeze(1))
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * batch.size(0)

        # --- VALIDATION PHASE ---
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch_tuple in test_loader:
                batch = batch_tuple[0]
                reconstructed = model(batch)
                loss = criterion(reconstructed, batch.squeeze(1))
                val_loss += loss.item() * batch.size(0)

        avg_train = train_loss / len(train_tensor)
        avg_val = val_loss / len(test_tensor)

        if (epoch + 1) % 10 == 0:
            print(f"Epoch [{epoch + 1}/{epochs}] | Train Loss: {avg_train:.6f} | Val Loss: {avg_val:.6f}")

    print("Training Complete")

    # Save the Weights
    save_path = "mutant_autoencoder.pth"
    torch.save(model.state_dict(), save_path)
    print(f"Model successfully saved to {save_path}")

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(BASE_DIR, '../trcgen/master_collected_traces_v55.csv')
    train_offline_autoencoder(path, epochs=100, batch_size=32)
