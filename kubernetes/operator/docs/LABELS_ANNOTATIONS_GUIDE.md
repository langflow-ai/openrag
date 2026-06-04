# Custom Labels and Annotations Guide

This guide explains how to add custom labels and annotations to infrastructure resources (PVCs, Secrets, Services, ServiceAccounts) managed by the OpenRAG operator.


## Overview

The OpenRAG operator now supports adding custom labels and annotations to all infrastructure resources it creates. This enables integration with:

- **Backup tools** (Velero, Kasten K10)
- **Monitoring systems** (Prometheus, Datadog)
- **IAM/RBAC** (AWS IAM Roles, GCP Workload Identity, Azure Managed Identity)
- **Cost allocation** and resource tracking
- **Network policies** and service mesh configuration
- **GitOps metadata** and automation tools

## Label and Annotation Hierarchy

Labels and annotations are merged with the following priority (highest to lowest):

1. **Operator-managed labels** (cannot be overridden)
   - `app.kubernetes.io/name: openrag`
   - `app.kubernetes.io/instance: <cr-name>`
   - `app.kubernetes.io/component: <role>`
   - `app.kubernetes.io/managed-by: openrag-operator`

2. **Resource-specific labels/annotations** (e.g., `PersistenceSpec.Labels`)

3. **Component-level labels/annotations** (e.g., `ComponentSpec.ServiceAccountLabels`)

4. **Common resource labels/annotations** (e.g., `OpenRAGSpec.CommonResourceLabels`)

## API Fields

### Global Fields (OpenRAGSpec)

Apply to all infrastructure resources across all components:

```yaml
spec:
  commonResourceLabels:
    environment: production
    team: platform
  commonResourceAnnotations:
    monitoring.prometheus.io/scrape: "true"
```

### Component-Level Fields (ComponentSpec)

Apply to specific component resources (Frontend, Backend, Langflow, Docling components, Valkey):

```yaml
spec:
  backend:
    # ServiceAccount labels and annotations
    serviceAccountLabels:
      app-tier: backend
    serviceAccountAnnotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::123:role/backend"
    
    # Service labels and annotations
    serviceLabels:
      api: "true"
    serviceAnnotations:
      service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
    
    # Secret labels and annotations
    secretLabels:
      secret-type: env-config
    secretAnnotations:
      vault.hashicorp.com/agent-inject: "false"
```

### Storage-Level Fields (PersistenceSpec)

Apply to PersistentVolumeClaims:

```yaml
spec:
  backend:
    storage:
      enabled: true
      size: 20Gi
      labels:
        storage-tier: ssd
        backup-policy: daily
      annotations:
        volume.beta.kubernetes.io/storage-provisioner: ebs.csi.aws.com
```

## Use Cases

### 1. AWS IAM Roles for Service Accounts (IRSA)

```yaml
spec:
  backend:
    serviceAccountAnnotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::123456789012:role/openrag-backend"
```

### 2. GCP Workload Identity

```yaml
spec:
  langflow:
    serviceAccountAnnotations:
      iam.gke.io/gcp-service-account: "openrag@project.iam.gserviceaccount.com"
```

### 3. Velero Backup Configuration

```yaml
spec:
  commonResourceAnnotations:
    monitoring.prometheus.io/scrape: "true"
  
  backend:
    storage:
      annotations:
        backup.velero.io/backup-volumes-excludes: "temp-volume,cache-volume"
```

### 4. Prometheus Monitoring

```yaml
spec:
  commonResourceLabels:
    monitoring: enabled
  
  backend:
    serviceLabels:
      prometheus.io/scrape: "true"
      prometheus.io/port: "8000"
```

### 5. Cost Allocation and Tracking

```yaml
spec:
  commonResourceLabels:
    cost-center: "12345"
    team: ai-platform
    environment: production
```

### 6. Network Policies and Service Mesh

```yaml
spec:
  backend:
    serviceLabels:
      network-policy: backend-tier
      istio-injection: enabled
```

### 7. Storage Policies

```yaml
spec:
  langflow:
    storage:
      labels:
        storage-tier: premium
        retention-policy: long-term
        backup-frequency: daily
      annotations:
        snapshot.storage.kubernetes.io/is-default-class: "true"
```

## Resource Coverage

The following resources support custom labels and annotations:

| Resource Type | Global Labels/Annotations | Component Labels/Annotations | Resource-Specific Labels/Annotations |
|---------------|---------------------------|------------------------------|--------------------------------------|
| **PersistentVolumeClaims** | ✅ CommonResourceLabels/Annotations | ❌ | ✅ PersistenceSpec.Labels/Annotations |
| **Secrets** | ✅ CommonResourceLabels/Annotations | ✅ SecretLabels/SecretAnnotations | ❌ |
| **Services** | ✅ CommonResourceLabels/Annotations | ✅ ServiceLabels/ServiceAnnotations | ❌ |
| **ServiceAccounts** | ✅ CommonResourceLabels/Annotations | ✅ ServiceAccountLabels/ServiceAccountAnnotations | ❌ |

## Protected Labels

The following labels are managed by the operator and cannot be overridden:

- `app.kubernetes.io/name`
- `app.kubernetes.io/instance`
- `app.kubernetes.io/component`
- `app.kubernetes.io/managed-by`

Attempting to override these labels will result in the operator-managed values taking precedence.

## Protected Annotations

For `.env` secrets (backend and langflow), the following annotation is always present and cannot be removed:

- `openr.ag/immutable: "true"`

This annotation is used by the operator to protect critical configuration secrets.

## Validation Rules

- Maximum 64 labels per field
- Maximum 64 annotations per field
- Label keys and values must follow Kubernetes naming conventions
- Annotation keys must follow Kubernetes naming conventions

## Examples

See the complete example in `config/samples/openrag_v1alpha1_openrag-with-labels-annotations.yaml`.

### Minimal Example

```yaml
apiVersion: openr.ag/v1alpha1
kind: OpenRAG
metadata:
  name: openrag-minimal
spec:
  commonResourceLabels:
    environment: dev
  
  frontend:
    image: quay.io/langflow-ai/openrag-frontend:latest
  
  backend:
    image: quay.io/langflow-ai/openrag-backend:latest
    serviceAccountAnnotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::123:role/backend"
  
  langflow:
    image: quay.io/langflow-ai/openrag-langflow:latest
```

### Advanced Example with All Features

```yaml
apiVersion: openr.ag/v1alpha1
kind: OpenRAG
metadata:
  name: openrag-advanced
spec:
  # Global labels for all resources
  commonResourceLabels:
    environment: production
    team: ai-platform
    cost-center: "12345"
  
  # Global annotations for all resources
  commonResourceAnnotations:
    monitoring.prometheus.io/scrape: "true"
    description: "OpenRAG infrastructure resources"
  
  backend:
    image: quay.io/langflow-ai/openrag-backend:latest
    
    # IAM role for AWS
    serviceAccountAnnotations:
      eks.amazonaws.com/role-arn: "arn:aws:iam::123:role/backend"
    
    # Service mesh and monitoring
    serviceLabels:
      istio-injection: enabled
      api-tier: backend
    
    # Storage with backup policy
    storage:
      enabled: true
      size: 50Gi
      labels:
        storage-tier: premium-ssd
        backup-policy: hourly
      annotations:
        volume.beta.kubernetes.io/storage-provisioner: ebs.csi.aws.com
```

## Migration Guide

Existing OpenRAG deployments will continue to work without any changes. The new label and annotation fields are optional and backward compatible.

To add labels and annotations to an existing deployment:

1. Update your OpenRAG CR with the desired labels and annotations
2. Apply the updated CR: `kubectl apply -f your-openrag-cr.yaml`
3. The operator will update resources on the next reconciliation

**Note:** PVCs are immutable once bound, so PVC labels and annotations are only applied during creation. To update PVC labels/annotations, you must delete and recreate the PVC (which will result in data loss unless you have backups).

## Troubleshooting

### Labels Not Appearing on Resources

1. Verify the CR has been applied: `kubectl get openrag <name> -o yaml`
2. Check operator logs: `kubectl logs -n openrag-system deployment/openrag-operator-controller-manager`
3. Ensure labels don't conflict with protected operator-managed labels

### Annotations Not Working

1. Check for typos in annotation keys
2. Verify the annotation is supported by the target resource type
3. For IAM annotations, ensure the IAM role exists and has the correct trust policy

### PVC Labels Not Updating

PVCs are immutable once bound. To update PVC labels:
1. Back up your data
2. Delete the PVC
3. Update the CR with new labels
4. Recreate the PVC (operator will apply new labels)
5. Restore your data

## Best Practices

1. **Use common labels for organization-wide policies**: Apply `commonResourceLabels` for labels that should be on all resources (environment, team, cost-center).

2. **Use component-specific labels for targeted policies**: Apply component-level labels for resource-specific needs (IAM roles, monitoring, network policies).

3. **Document your labeling strategy**: Maintain documentation of your label taxonomy and what each label means.

4. **Test in non-production first**: Always test label and annotation changes in a development environment before applying to production.

5. **Use annotations for external tool integration**: Annotations are ideal for configuration that external tools (backup, monitoring, IAM) need to read.

6. **Keep labels simple and consistent**: Use lowercase, hyphen-separated values for better readability and consistency.

## Technical Details

### Map Ordering and Reconciliation

You might wonder: "Since Go maps have random iteration order, won't this cause unnecessary pod restarts?"

**Answer: No.** The operator is designed to handle this correctly:

1. **Hash-based change detection**: The operator uses a `desiredHash()` function that computes a SHA256 hash of the entire resource
2. **Deterministic JSON marshaling**: The hash is computed from `json.Marshal()`, which sorts map keys alphabetically
3. **Consistent hashing**: Resources with identical content produce identical hashes, regardless of the order in which maps were built

This means:
- Labels and annotations can be merged in any order during reconciliation
- The resulting hash will always be the same for identical content
- No unnecessary updates or pod restarts occur due to map ordering

This behavior is verified by unit tests in `internal/controller/label_merge_test.go`.

## Related Documentation

- [Kubernetes Labels and Selectors](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/)
- [Kubernetes Annotations](https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations/)
- [AWS IAM Roles for Service Accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [GCP Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
- [Velero Backup Annotations](https://velero.io/docs/main/resource-filtering/)