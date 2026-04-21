# OpenRAG Operator Makefile
#
# Go version: managed via gvm.  The Makefile auto-selects go1.26.0 when found
# under ~/.gvm/gos/go1.26.0, otherwise falls back to whatever 'go' is in PATH.
#
# Quick start:
#   make deps          # install controller-gen, kustomize, envtest into ./bin
#   make manifests     # generate CRD + RBAC YAML under config/
#   make generate      # regenerate zz_generated.deepcopy.go
#   make build         # compile the operator binary

# Image to push/pull for the operator container.
IMG ?= ghcr.io/langflow-ai/openrag-operator:latest

# Kubernetes version used by envtest.
ENVTEST_K8S_VERSION = 1.33.0

# Go 1.26.0 via gvm — set PATH and GOROOT so sub-shells pick the right toolchain.
GVM_GO_VERSION   ?= go1.26.0
GVM_GO_ROOT      := $(HOME)/.gvm/gos/$(GVM_GO_VERSION)
ifneq ($(wildcard $(GVM_GO_ROOT)/bin/go),)
  export GOROOT := $(GVM_GO_ROOT)
  export PATH   := $(GVM_GO_ROOT)/bin:$(PATH)
endif

# Resolve GOBIN (respect GOBIN env if set, else fall back to GOPATH/bin).
ifeq (,$(shell go env GOBIN))
GOBIN=$(shell go env GOPATH)/bin
else
GOBIN=$(shell go env GOBIN)
endif

CONTAINER_TOOL ?= docker
SHELL = /usr/bin/env bash -o pipefail
.SHELLFLAGS = -ec

.PHONY: all
all: build

##@ General

.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

.PHONY: manifests
manifests: controller-gen ## Generate CRD and RBAC manifests from Go type markers.
	$(CONTROLLER_GEN) rbac:roleName=manager-role crd paths="./..." \
		output:crd:artifacts:config=config/crd/bases \
		output:rbac:artifacts:config=config/rbac

.PHONY: generate
generate: controller-gen ## Regenerate zz_generated.deepcopy.go from type definitions.
	$(CONTROLLER_GEN) object:headerFile="hack/boilerplate.go.txt" paths="./..."

.PHONY: fmt
fmt: ## Run go fmt.
	go fmt ./...

.PHONY: vet
vet: ## Run go vet.
	go vet ./...

.PHONY: tidy
tidy: ## Run go mod tidy.
	go mod tidy

.PHONY: lint
lint: golangci-lint ## Run golangci-lint.
	$(GOLANGCI_LINT) run ./...

.PHONY: test
test: manifests generate fmt vet envtest ## Run unit tests.
	KUBEBUILDER_ASSETS="$(shell $(ENVTEST) use $(ENVTEST_K8S_VERSION) --bin-dir $(LOCALBIN) -p path)" \
		go test $$(go list ./... | grep -v /e2e) -coverprofile cover.out

##@ Build

.PHONY: build
build: manifests generate fmt vet ## Build the operator binary to bin/manager.
	go build -o bin/manager cmd/main.go

.PHONY: run
run: manifests generate fmt vet ## Run the operator locally (uses current kubeconfig).
	go run ./cmd/main.go

.PHONY: docker-build
docker-build: ## Build the operator container image.
	$(CONTAINER_TOOL) build -t $(IMG) .

.PHONY: docker-push
docker-push: ## Push the operator container image.
	$(CONTAINER_TOOL) push $(IMG)

.PHONY: docker-buildx
docker-buildx: ## Build and push multi-arch image via buildx.
	$(CONTAINER_TOOL) buildx build --platform linux/amd64,linux/arm64 --push -t $(IMG) .

##@ Deployment

ifndef ignore-not-found
  ignore-not-found = false
endif

.PHONY: install
install: manifests kustomize ## Install CRDs into the cluster in ~/.kube/config.
	$(KUSTOMIZE) build config/crd | kubectl apply -f -

.PHONY: uninstall
uninstall: manifests kustomize ## Uninstall CRDs from the cluster.
	$(KUSTOMIZE) build config/crd | kubectl delete --ignore-not-found=$(ignore-not-found) -f -

.PHONY: deploy
deploy: manifests kustomize ## Deploy the operator to the cluster.
	cd config/manager && $(KUSTOMIZE) edit set image controller=$(IMG)
	$(KUSTOMIZE) build config/default | kubectl apply -f -

.PHONY: undeploy
undeploy: kustomize ## Remove the operator from the cluster.
	$(KUSTOMIZE) build config/default | kubectl delete --ignore-not-found=$(ignore-not-found) -f -

.PHONY: dist
dist: manifests kustomize ## Build a single-file install manifest to dist/install.yaml.
	mkdir -p dist
	$(KUSTOMIZE) build config/default > dist/install.yaml

##@ Dependencies

LOCALBIN ?= $(shell pwd)/bin
$(LOCALBIN):
	mkdir -p $(LOCALBIN)

KUBECTL              ?= kubectl
KUSTOMIZE            ?= $(LOCALBIN)/kustomize
CONTROLLER_GEN       ?= $(LOCALBIN)/controller-gen
ENVTEST              ?= $(LOCALBIN)/setup-envtest
GOLANGCI_LINT        ?= $(LOCALBIN)/golangci-lint

KUSTOMIZE_VERSION          ?= v5.4.3
CONTROLLER_TOOLS_VERSION   ?= v0.16.4
ENVTEST_VERSION            ?= release-0.19
GOLANGCI_LINT_VERSION      ?= v1.64.6

.PHONY: deps
deps: controller-gen kustomize envtest golangci-lint ## Install all local tool dependencies into ./bin.

.PHONY: kustomize
kustomize: $(KUSTOMIZE) ## Download kustomize locally if necessary.
$(KUSTOMIZE): $(LOCALBIN)
	$(call go-install-tool,$(KUSTOMIZE),sigs.k8s.io/kustomize/kustomize/v5,$(KUSTOMIZE_VERSION))

.PHONY: controller-gen
controller-gen: $(CONTROLLER_GEN) ## Download controller-gen locally if necessary.
$(CONTROLLER_GEN): $(LOCALBIN)
	$(call go-install-tool,$(CONTROLLER_GEN),sigs.k8s.io/controller-tools/cmd/controller-gen,$(CONTROLLER_TOOLS_VERSION))

.PHONY: envtest
envtest: $(ENVTEST) ## Download setup-envtest locally if necessary.
$(ENVTEST): $(LOCALBIN)
	$(call go-install-tool,$(ENVTEST),sigs.k8s.io/controller-runtime/tools/setup-envtest,$(ENVTEST_VERSION))

.PHONY: golangci-lint
golangci-lint: $(GOLANGCI_LINT) ## Download golangci-lint locally if necessary.
$(GOLANGCI_LINT): $(LOCALBIN)
	$(call go-install-tool,$(GOLANGCI_LINT),github.com/golangci/golangci-lint/cmd/golangci-lint,$(GOLANGCI_LINT_VERSION))

# go-install-tool installs a versioned binary into LOCALBIN, caching by version suffix.
# Usage: $(call go-install-tool,<target-path>,<package-url>,<version>)
define go-install-tool
@[ -f "$(1)-$(3)" ] || { \
set -e; \
package=$(2)@$(3) ;\
echo "Downloading $${package}" ;\
rm -f $(1) || true ;\
GOBIN=$(LOCALBIN) go install $${package} ;\
mv $(1) $(1)-$(3) ;\
} ;\
ln -sf $(1)-$(3) $(1)
endef
