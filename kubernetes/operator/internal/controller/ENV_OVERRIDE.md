# Environment Variable Override System

The OpenRAG operator implements a three-level environment variable override system that allows fine-grained control over environment variables for Langflow, Backend, and Frontend components.

## Three-Level Priority System

Environment variables are merged using the following priority (highest to lowest):

1. **CR Spec Env Vars** (Highest Priority) - Defined in the `OpenRAG` custom resource
2. **Operator Environment** (Medium Priority) - Set in the operator's deployment with component-specific prefixes
3. **Hardcoded Defaults** (Lowest Priority) - Built into the operator code

### Visual Representation

```
┌─────────────────────────────────────────────────────────────┐
│ Priority Level 3 (Highest): CR Spec                        │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ spec:                                                   │ │
│ │   langflow:                                            │ │
│ │     env:                                               │ │
│ │       - name: LANGFLOW_LOG_LEVEL                       │ │
│ │         value: "ERROR"                                 │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↓ overrides
┌─────────────────────────────────────────────────────────────┐
│ Priority Level 2 (Medium): Operator Environment            │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Operator Deployment:                                   │ │
│ │   env:                                                 │ │
│ │     - name: OPTLF_LANGFLOW_LOG_LEVEL                  │ │
│ │       value: "INFO"                                    │ │
│ │     - name: OPTLF_LANGFLOW_WORKERS                    │ │
│ │       value: "8"                                       │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ↓ overrides
┌─────────────────────────────────────────────────────────────┐
│ Priority Level 1 (Lowest): Hardcoded Defaults              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ env.go DefaultLangflowEnvVars:                        │ │
│ │   "LANGFLOW_LOG_LEVEL": "DEBUG"                       │ │
│ │   "LANGFLOW_WORKERS": "4"                             │ │
│ │   "LANGFLOW_AUTO_LOGIN": "true"                       │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Result

In the example above, the final merged environment would be:
- `LANGFLOW_LOG_LEVEL=ERROR` (from CR spec - highest priority)
- `LANGFLOW_WORKERS=8` (from operator env - medium priority)
- `LANGFLOW_AUTO_LOGIN=true` (from defaults - lowest priority)

## Component-Specific Prefixes

Each component has its own prefix for operator-level environment variables:

| Component | Prefix | Example |
|-----------|--------|---------|
| Langflow | `OPTLF_` | `OPTLF_LANGFLOW_WORKERS=8` |
| Backend | `OPTORBE_` | `OPTORBE_LOG_LEVEL=INFO` |
| Frontend | `OPTORFE_` | `OPTORFE_PORT=3000` |

This allows you to set different values for the same environment variable across components:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openrag-operator
spec:
  template:
    spec:
      containers:
      - name: manager
        env:
        - name: OPTLF_WORKERS
          value: "8"
        - name: OPTORBE_WORKERS
          value: "4"
        - name: OPTORFE_WORKERS
          value: "2"
```

## Usage Examples

### Example 1: Override with CR Spec

```yaml
apiVersion: openr.ag/v1alpha1
kind: OpenRAG
metadata:
  name: my-openrag
spec:
  langflow:
    env:
    - name: LANGFLOW_LOG_LEVEL
      value: "ERROR"
    - name: LANGFLOW_WORKERS
      value: "16"
```

### Example 2: Override with Operator Environment

Deploy the operator with custom defaults:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openrag-operator
spec:
  template:
    spec:
      containers:
      - name: manager
        env:
        # Langflow overrides
        - name: OPTLF_LANGFLOW_WORKERS
          value: "8"
        - name: OPTLF_LANGFLOW_LOG_LEVEL
          value: "INFO"

        # Backend overrides
        - name: OPTORBE_LOG_LEVEL
          value: "DEBUG"
        - name: OPTORBE_MAX_WORKERS
          value: "6"
```

### Example 3: Use All Three Levels

```yaml
# Operator deployment with medium-priority defaults
env:
- name: OPTLF_LANGFLOW_WORKERS
  value: "8"

---
# OpenRAG CR with high-priority overrides
apiVersion: openr.ag/v1alpha1
kind: OpenRAG
metadata:
  name: my-openrag
spec:
  langflow:
    env:
    - name: LANGFLOW_LOG_LEVEL
      value: "ERROR"
```

**Result:**
- `LANGFLOW_WORKERS=8` (from operator env, overrides default "4")
- `LANGFLOW_LOG_LEVEL=ERROR` (from CR, overrides operator env if set)
- `LANGFLOW_AUTO_LOGIN=true` (from hardcoded defaults)

## API Reference

### EnvVarManager

```go
type EnvVarManager struct {
    Config                  config.OperatorConfig
    DefaultLangflowEnvVars  map[string]string
    DefaultOpenRagBEEnvVars map[string]string
    DefaultOpenRagFEEnvVars map[string]string
}
```

### Methods

#### GetLangflowEnvVars

```go
func (m *EnvVarManager) GetLangflowEnvVars(crEnvVars []corev1.EnvVar) map[string]string
```

Returns merged Langflow environment variables with three-level priority applied.

#### GetBackendEnvVars

```go
func (m *EnvVarManager) GetBackendEnvVars(crEnvVars []corev1.EnvVar) map[string]string
```

Returns merged Backend environment variables with three-level priority applied.

#### GetFrontendEnvVars

```go
func (m *EnvVarManager) GetFrontendEnvVars(crEnvVars []corev1.EnvVar) map[string]string
```

Returns merged Frontend environment variables with three-level priority applied.

#### BuildEnvFileContent

```go
func (m *EnvVarManager) BuildEnvFileContent(envVars map[string]string) string
```

Converts a map of environment variables to `.env` file format.

## Implementation Details

### Priority Merge Algorithm

1. **Start with defaults**: Copy all hardcoded defaults to result map
2. **Apply operator env**: Iterate through operator's environment, find variables with the correct prefix, strip prefix, and override
3. **Apply CR env**: Iterate through CR spec env vars, override with their values (only direct values, not `valueFrom`)

### Prefix Stripping

When the operator environment contains `OPTLF_LANGFLOW_WORKERS=8`, the prefix `OPTLF_` is stripped, resulting in `LANGFLOW_WORKERS=8` in the final environment.

### ValueFrom Support

CR env vars using `valueFrom` (e.g., secrets, configmaps) are NOT evaluated at this stage. They are passed directly to the pod spec and resolved by Kubernetes at runtime. Only env vars with direct `value` fields are merged into the `.env` file.

## Testing

See `env_test.go` for comprehensive test coverage of:
- Three-level priority override
- Prefix filtering
- CR env var override
- Empty CR env vars
- ValueFrom handling
- Real-world scenarios

Run tests:
```bash
go test -v ./internal/controller -run TestEnvVarManager
```

## Best Practices

1. **Use CR spec for instance-specific overrides**: Each OpenRAG instance can have custom settings
2. **Use operator env for organization-wide defaults**: Set in operator deployment for all instances
3. **Modify hardcoded defaults sparingly**: Only change when updating the operator version
4. **Use descriptive names**: Operator env vars include the component in the name (e.g., `OPTLF_LANGFLOW_WORKERS`)
5. **Document overrides**: Use comments in your CRs and operator deployment to explain why overrides are needed
