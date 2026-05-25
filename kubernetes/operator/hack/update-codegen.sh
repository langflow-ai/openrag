#!/usr/bin/env bash

# Copyright The OpenRAG Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_ROOT=$(dirname "${BASH_SOURCE[0]}")/..

# Find code-generator in go module cache
CODEGEN_PKG=$(go list -f '{{.Dir}}' -m k8s.io/code-generator)

if [ -z "${CODEGEN_PKG}" ] || [ ! -d "${CODEGEN_PKG}" ]; then
  echo "Error: k8s.io/code-generator not found in module cache"
  echo "Please run: go get k8s.io/code-generator@v0.33.0"
  exit 1
fi

echo "Using code-generator from: ${CODEGEN_PKG}"

# Ensure the output directory structure exists
mkdir -p "${SCRIPT_ROOT}/pkg/generated"

# Source the kube_codegen library
source "${CODEGEN_PKG}/kube_codegen.sh"

# Generate clientset for API types
# Run from the module root directory
# --with-watch enables generation of listers and informers
kube::codegen::gen_client \
  --with-watch \
  --one-input-api "api/v1alpha1" \
  --output-dir "${SCRIPT_ROOT}/pkg/generated" \
  --output-pkg "github.com/langflow-ai/openrag-operator/pkg/generated" \
  --boilerplate "${SCRIPT_ROOT}/hack/boilerplate.go.txt" \
  "${SCRIPT_ROOT}"

echo ""
echo "✅ Code generation complete!"
echo ""
echo "Generated files:"
echo "  - pkg/generated/clientset/versioned/      (Typed clientset)"
echo "  - pkg/generated/listers/api/v1alpha1/     (Listers)"
echo "  - pkg/generated/informers/externalversions/ (Informers)"
echo ""
echo "Users can now import:"
echo "  import clientset \"github.com/langflow-ai/openrag-operator/pkg/generated/clientset/versioned\""
