/**
 *  Copyright (c) 2023 by Contributors
 * @file graphbolt/src/serialize.cc
 * @brief Source file of serialize.
 */

#include <graphbolt/serialize.h>
#include <torch/torch.h>

namespace torch {

serialize::InputArchive& operator>>(
    serialize::InputArchive& archive,
    graphbolt::sampling::FusedCSCSamplingGraph& graph) {
  graph.Load(archive);
  return archive;
}

serialize::OutputArchive& operator<<(
    serialize::OutputArchive& archive,
    const graphbolt::sampling::FusedCSCSamplingGraph& graph) {
  graph.Save(archive);
  return archive;
}

}  // namespace torch

namespace graphbolt {

torch::IValue read_from_archive(
    torch::serialize::InputArchive& archive, const std::string& key) {
  torch::IValue data;
  archive.read(key, data);
  return data;
}

}  // namespace graphbolt
