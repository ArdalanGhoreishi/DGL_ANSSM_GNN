"""
This example shows how to create a GraphBolt dataloader to sample and train a
link prediction model with the Cora dataset.

Disclaimer: Please note that the test edges are not excluded from the original
graph in the dataset, which could lead to data leakage. We are ignoring this
issue for this example because we are focused on demonstrating usability.
"""

import dgl.graphbolt as gb
import torch
import torch.nn as nn
import torch.nn.functional as F
from dgl.nn import SAGEConv
from torcheval.metrics import BinaryAUROC


############################################################################
# (HIGHLIGHT) Create a single process dataloader with dgl graphbolt package.
############################################################################
def create_dataloader(dateset, device, is_train=True):
    # The second of two tasks in the dataset is link prediction.
    task = dataset.tasks[1]
    itemset = task.train_set if is_train else task.test_set

    # Sample seed edges from the itemset.
    datapipe = gb.ItemSampler(itemset, batch_size=256)

    if is_train:
        # Sample negative edges for the seed edges.
        datapipe = datapipe.sample_uniform_negative(
            dataset.graph, negative_ratio=1
        )

        # Sample neighbors for the seed nodes.
        datapipe = datapipe.sample_neighbor(dataset.graph, fanouts=[4, 2])

        # Exclude seed edges from the subgraph.
        datapipe = datapipe.transform(gb.exclude_seed_edges)

    else:
        # Sample neighbors for the seed nodes.
        datapipe = datapipe.sample_neighbor(dataset.graph, fanouts=[-1, -1])

    # Fetch features for sampled nodes.
    datapipe = datapipe.fetch_feature(
        dataset.feature, node_feature_keys=["feat"]
    )

    # Copy the mini-batch to the designated device for training.
    datapipe = datapipe.copy_to(device)

    # Initiate the dataloader for the datapipe.
    return gb.DataLoader(datapipe)


class GraphSAGE(nn.Module):
    def __init__(self, in_size, hidden_size=16):
        super().__init__()
        self.layers = nn.ModuleList()
        self.layers.append(SAGEConv(in_size, hidden_size, "mean"))
        self.layers.append(SAGEConv(hidden_size, hidden_size, "mean"))
        self.predictor = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self, blocks, x):
        hidden_x = x
        for layer_idx, (layer, block) in enumerate(zip(self.layers, blocks)):
            hidden_x = layer(block, hidden_x)
            is_last_layer = layer_idx == len(self.layers) - 1
            if not is_last_layer:
                hidden_x = F.relu(hidden_x)
        return hidden_x


def to_binary_link_dgl_computing_pack(data: gb.MiniBatch):
    """Convert the minibatch to a training pair and a label tensor."""
    pos_src, pos_dst = data.positive_node_pairs
    neg_src, neg_dst = data.negative_node_pairs
    node_pairs = (
        torch.cat((pos_src, neg_src), dim=0),
        torch.cat((pos_dst, neg_dst), dim=0),
    )
    pos_label = torch.ones_like(pos_src)
    neg_label = torch.zeros_like(neg_src)
    labels = torch.cat([pos_label, neg_label], dim=0)
    return (node_pairs, labels)


@torch.no_grad()
def evaluate(model, dataset, device):
    model.eval()
    dataloader = create_dataloader(dataset, device, is_train=False)

    logits = []
    labels = []
    for step, data in enumerate(dataloader):
        # Convert data to DGL format for computing.
        data = data.to_dgl()

        # Unpack MiniBatch.
        compacted_pairs, label = to_binary_link_dgl_computing_pack(data)

        # The features of sampled nodes.
        x = data.node_features["feat"]

        # Forward.
        y = model(data.blocks, x)
        logit = (
            model.predictor(y[compacted_pairs[0]] * y[compacted_pairs[1]])
            .squeeze()
            .detach()
        )

        logits.append(logit)
        labels.append(label)

    logits = torch.cat(logits, dim=0)
    labels = torch.cat(labels, dim=0)

    # Compute the AUROC score.
    metric = BinaryAUROC()
    metric.update(logits, labels)
    score = metric.compute().item()
    print(f"AUC: {score:.3f}")


def train(model, dataset, device):
    dataloader = create_dataloader(dataset, device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)

    for epoch in range(10):
        model.train()
        total_loss = 0
        ########################################################################
        # (HIGHLIGHT) Iterate over the dataloader and train the model with all
        # mini-batches.
        ########################################################################
        for step, data in enumerate(dataloader):
            # Convert data to DGL format for computing.
            data = data.to_dgl()

            # Unpack MiniBatch.
            compacted_pairs, labels = to_binary_link_dgl_computing_pack(data)

            # The features of sampled nodes.
            x = data.node_features["feat"]

            # Forward.
            y = model(data.blocks, x)
            logits = model.predictor(
                y[compacted_pairs[0]] * y[compacted_pairs[1]]
            ).squeeze()

            # Compute loss.
            loss = F.binary_cross_entropy_with_logits(logits, labels.float())

            # Backward.
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()

        print(f"Epoch {epoch:03d} | Loss {total_loss / (step + 1):.3f}")


if __name__ == "__main__":
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"Training in {device} mode.")

    # Load and preprocess dataset.
    print("Loading data...")
    dataset = gb.BuiltinDataset("cora").load()

    in_size = dataset.feature.size("node", None, "feat")[0]
    model = GraphSAGE(in_size).to(device)

    # Model training.
    print("Training...")
    train(model, dataset, device)

    # Test the model.
    print("Testing...")
    evaluate(model, dataset, device)
