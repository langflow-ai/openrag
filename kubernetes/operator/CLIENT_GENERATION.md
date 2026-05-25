# Typed Kubernetes Client Generation for OpenRAG

This document explains how to generate and use typed Kubernetes clients for the OpenRAG CRDs.

## Overview

Instead of using `unstructured.Unstructured`, you can now use strongly-typed Go clients that provide:
- **Compile-time type safety** - Catch errors during development, not runtime
- **IDE auto-completion** - Better developer experience
- **Cleaner code** - No manual field path navigation or type assertions

## Generating the Clientset

### Prerequisites

```bash
# Install code-generator dependency
go get k8s.io/code-generator@v0.33.0
```

### Generate Clients

```bash
# Generate clientset, listers, and informers
make generate-client
```

This will create the following packages:
- `pkg/generated/clientset/versioned` - Typed clientset
- `pkg/generated/listers/api/v1alpha1` - Listers for efficient reads
- `pkg/generated/informers/externalversions` - Informers for watching resources

## Usage Examples

### Before (Using Unstructured)

```go
import (
    "k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
    "k8s.io/apimachinery/pkg/runtime/schema"
)

// Create unstructured client
dynamicClient, err := dynamic.NewForConfig(config)
gvr := schema.GroupVersionResource{
    Group:    "openr.ag",
    Version:  "v1alpha1",
    Resource: "openrags",
}

// Get OpenRAG (weakly typed - runtime errors)
obj, err := dynamicClient.Resource(gvr).Namespace("default").Get(ctx, "my-openrag", metav1.GetOptions{})
if err != nil {
    return err
}

// Manual field navigation (error-prone)
spec, found, err := unstructured.NestedMap(obj.Object, "spec")
backend, found, err := unstructured.NestedMap(spec, "backend")
image, found, err := unstructured.NestedString(backend, "image")
// No compile-time type checking!
```

### After (Using Typed Client)

```go
import (
    openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
    clientset "github.com/langflow-ai/openrag-operator/pkg/generated/clientset/versioned"
)

// Create typed client
client, err := clientset.NewForConfig(config)

// Get OpenRAG (strongly typed - compile-time safety!)
openrag, err := client.OpenrV1alpha1().OpenRAGs("default").Get(ctx, "my-openrag", metav1.GetOptions{})
if err != nil {
    return err
}

// Direct field access with type safety
image := openrag.Spec.Backend.Image  // ✅ Type-safe!
replicas := openrag.Spec.Backend.Replicas  // ✅ Auto-complete!
```

## Full Example: Creating an OpenRAG Instance

```go
package main

import (
    "context"
    "fmt"

    corev1 "k8s.io/api/core/v1"
    "k8s.io/apimachinery/pkg/api/resource"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/tools/clientcmd"
    "k8s.io/utils/ptr"

    openragv1alpha1 "github.com/langflow-ai/openrag-operator/api/v1alpha1"
    clientset "github.com/langflow-ai/openrag-operator/pkg/generated/clientset/versioned"
)

func main() {
    // Load kubeconfig
    config, err := clientcmd.BuildConfigFromFlags("", "/path/to/kubeconfig")
    if err != nil {
        panic(err)
    }

    // Create OpenRAG typed client
    client, err := clientset.NewForConfig(config)
    if err != nil {
        panic(err)
    }

    // Define OpenRAG instance
    openrag := &openragv1alpha1.OpenRAG{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "my-openrag",
            Namespace: "default",
        },
        Spec: openragv1alpha1.OpenRAGSpec{
            TenantID: "tenant-123",
            Frontend: openragv1alpha1.FrontendSpec{
                ComponentSpec: openragv1alpha1.ComponentSpec{
                    Image:    "myregistry/openrag-frontend:v1.0.0",
                    Replicas: ptr.To(int32(2)),
                    Resources: corev1.ResourceRequirements{
                        Requests: corev1.ResourceList{
                            corev1.ResourceCPU:    resource.MustParse("100m"),
                            corev1.ResourceMemory: resource.MustParse("256Mi"),
                        },
                    },
                },
            },
            Backend: openragv1alpha1.BackendSpec{
                ComponentSpec: openragv1alpha1.ComponentSpec{
                    Image:    "myregistry/openrag-backend:v1.0.0",
                    Replicas: ptr.To(int32(3)),
                    Env: []corev1.EnvVar{
                        {Name: "CUSTOM_VAR", Value: "custom_value"},
                    },
                },
                Storage: &openragv1alpha1.PersistenceSpec{
                    Enabled: true,
                    Size:    resource.MustParse("10Gi"),
                },
            },
            Langflow: openragv1alpha1.LangflowSpec{
                ComponentSpec: openragv1alpha1.ComponentSpec{
                    Image:    "myregistry/langflow:v1.0.0",
                    Replicas: ptr.To(int32(2)),
                },
                PVCReclaimPolicy: openragv1alpha1.PVCReclaimRetain,
            },
        },
    }

    // Create the resource
    result, err := client.OpenrV1alpha1().OpenRAGs("default").Create(
        context.Background(),
        openrag,
        metav1.CreateOptions{},
    )
    if err != nil {
        panic(err)
    }

    fmt.Printf("Created OpenRAG: %s\n", result.Name)

    // Update the resource
    result.Spec.Backend.Replicas = ptr.To(int32(5))
    updated, err := client.OpenrV1alpha1().OpenRAGs("default").Update(
        context.Background(),
        result,
        metav1.UpdateOptions{},
    )
    if err != nil {
        panic(err)
    }

    fmt.Printf("Updated OpenRAG backend replicas to: %d\n", *updated.Spec.Backend.Replicas)

    // List all OpenRAG instances
    list, err := client.OpenrV1alpha1().OpenRAGs("").List(
        context.Background(),
        metav1.ListOptions{},
    )
    if err != nil {
        panic(err)
    }

    fmt.Printf("Found %d OpenRAG instances\n", len(list.Items))
    for _, item := range list.Items {
        fmt.Printf("  - %s/%s (Phase: %s)\n", item.Namespace, item.Name, item.Status.Phase)
    }
}
```

## Using Informers (Efficient Watching)

Informers provide efficient caching and watching of resources:

```go
import (
    "time"

    "k8s.io/client-go/tools/cache"

    informers "github.com/langflow-ai/openrag-operator/pkg/generated/informers/externalversions"
)

// Create informer factory
informerFactory := informers.NewSharedInformerFactory(client, time.Minute*10)

// Get OpenRAG informer
openragInformer := informerFactory.Openr().V1alpha1().OpenRAGs()

// Add event handlers
openragInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
    AddFunc: func(obj interface{}) {
        openrag := obj.(*openragv1alpha1.OpenRAG)
        fmt.Printf("OpenRAG added: %s/%s\n", openrag.Namespace, openrag.Name)
    },
    UpdateFunc: func(old, new interface{}) {
        newOpenRAG := new.(*openragv1alpha1.OpenRAG)
        fmt.Printf("OpenRAG updated: %s/%s\n", newOpenRAG.Namespace, newOpenRAG.Name)
    },
    DeleteFunc: func(obj interface{}) {
        openrag := obj.(*openragv1alpha1.OpenRAG)
        fmt.Printf("OpenRAG deleted: %s/%s\n", openrag.Namespace, openrag.Name)
    },
})

// Start informers
stopCh := make(chan struct{})
defer close(stopCh)
informerFactory.Start(stopCh)

// Wait for cache sync
if !cache.WaitForCacheSync(stopCh, openragInformer.Informer().HasSynced) {
    panic("Failed to sync cache")
}

// Now use the lister for efficient reads
lister := openragInformer.Lister()
openrags, err := lister.OpenRAGs("default").List(labels.Everything())
```

## Benefits

### Type Safety
```go
// ❌ Unstructured - Runtime error
image := obj.Object["spec"].(map[string]interface{})["backend"].(map[string]interface{})["image"].(string)

// ✅ Typed - Compile-time error if field doesn't exist
image := openrag.Spec.Backend.Image
```

### IDE Support
- Auto-completion for all fields
- Jump to definition
- Inline documentation
- Refactoring support

### Cleaner Code
- No type assertions
- No manual field path navigation
- Easier to read and maintain

## Regenerating Clients

Run this command whenever you modify the CRD types:

```bash
make generate        # Regenerate DeepCopy methods
make generate-client # Regenerate clientsets, listers, informers
```

## Distribution

### Option 1: Publish as Go Module (Recommended)

Users can import directly:

```go
import clientset "github.com/langflow-ai/openrag-operator/pkg/generated/clientset/versioned"
```

### Option 2: Copy Generated Code

If users don't want to depend on your entire module, they can copy the generated code to their project:

```bash
cp -r pkg/generated /path/to/their/project/
```

## Troubleshooting

### `code-generator` not found

If you see this error:
```
Error: k8s.io/code-generator not found in module cache
```

Run:
```bash
go mod download k8s.io/code-generator
# OR
go get k8s.io/code-generator@v0.33.0
go mod tidy
```

The dependency is already in `go.mod`, so `go mod download` should be sufficient.

### Permission denied on script

```bash
chmod +x hack/update-codegen.sh
```

### Generated code not in version control

It's recommended to commit generated code to version control so users can use it without running code generation.

### CI Check Failures

If your pull request fails with:

```text
Error: git diff --exit-code pkg/generated/
```

This means you modified the API types but didn't regenerate the typed client. Fix it:

```bash
make generate-client
git add pkg/generated/
git commit --amend --no-edit
git push --force-with-lease
```

Our CI automatically verifies that generated code is up to date to prevent inconsistencies.

## Contributing

When modifying API types in `api/v1alpha1/`, always run:

```bash
make generate        # Regenerate deepcopy code
make manifests       # Regenerate CRDs and RBAC
make generate-client # Regenerate typed client
git add api/ config/ pkg/generated/
git commit -m "feat: add new field to OpenRAG spec"
```

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for more details.

## References

- [Kubernetes Code Generator](https://github.com/kubernetes/code-generator)
- [Sample Controller](https://github.com/kubernetes/sample-controller)
- [Client-go Documentation](https://github.com/kubernetes/client-go)
