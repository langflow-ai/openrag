{{/*
Expand the name of the chart.
*/}}
{{- define "bomarag.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
If tenant name is provided, prefix with tenant name.
*/}}
{{- define "bomarag.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if .Values.global.tenant.name }}
{{- printf "%s-%s" .Values.global.tenant.name $name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s" $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create the namespace name.
Uses tenant namespace if specified, otherwise tenant name, otherwise release namespace.
*/}}
{{- define "bomarag.namespace" -}}
{{- if .Values.global.tenant.namespace }}
{{- .Values.global.tenant.namespace }}
{{- else if .Values.global.tenant.name }}
{{- .Values.global.tenant.name }}
{{- else }}
{{- .Release.Namespace }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "bomarag.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "bomarag.labels" -}}
helm.sh/chart: {{ include "bomarag.chart" . }}
{{ include "bomarag.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.global.tenant.name }}
bomarag.io/tenant: {{ .Values.global.tenant.name }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "bomarag.selectorLabels" -}}
app.kubernetes.io/name: {{ include "bomarag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "bomarag.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "bomarag.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Langflow component labels
*/}}
{{- define "bomarag.langflow.labels" -}}
{{ include "bomarag.labels" . }}
app.kubernetes.io/component: langflow
{{- end }}

{{/*
Langflow selector labels
*/}}
{{- define "bomarag.langflow.selectorLabels" -}}
{{ include "bomarag.selectorLabels" . }}
app.kubernetes.io/component: langflow
{{- end }}

{{/*
Backend component labels
*/}}
{{- define "bomarag.backend.labels" -}}
{{ include "bomarag.labels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Backend selector labels
*/}}
{{- define "bomarag.backend.selectorLabels" -}}
{{ include "bomarag.selectorLabels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Frontend component labels
*/}}
{{- define "bomarag.frontend.labels" -}}
{{ include "bomarag.labels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Frontend selector labels
*/}}
{{- define "bomarag.frontend.selectorLabels" -}}
{{ include "bomarag.selectorLabels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Dashboards component labels
*/}}
{{- define "bomarag.dashboards.labels" -}}
{{ include "bomarag.labels" . }}
app.kubernetes.io/component: dashboards
{{- end }}

{{/*
Dashboards selector labels
*/}}
{{- define "bomarag.dashboards.selectorLabels" -}}
{{ include "bomarag.selectorLabels" . }}
app.kubernetes.io/component: dashboards
{{- end }}

{{/*
Generate the Langflow service URL
*/}}
{{- define "bomarag.langflow.url" -}}
http://{{ include "bomarag.fullname" . }}-langflow:{{ .Values.langflow.service.port }}
{{- end }}

{{/*
Generate the Backend service URL
*/}}
{{- define "bomarag.backend.url" -}}
http://{{ include "bomarag.fullname" . }}-backend:{{ .Values.backend.service.port }}
{{- end }}

{{/*
Generate the general OpenSearch Host
*/}}
{{- define "bomarag.opensearch.host" -}}
{{- if .Values.global.opensearch.host -}}
{{- .Values.global.opensearch.host -}}
{{- else -}}
{{- printf "%s-opensearch.%s.svc.cluster.local" (include "bomarag.fullname" .) .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{/*
Generate the OpenSearch URL
*/}}
{{- define "bomarag.opensearch.url" -}}
{{ .Values.global.opensearch.scheme }}://{{ include "bomarag.opensearch.host" . }}:{{ .Values.global.opensearch.port }}
{{- end }}

{{/*
Generate the Langflow-specific OpenSearch Host
*/}}
{{- define "bomarag.langflow.opensearch.host" -}}
{{- if .Values.global.opensearch.langflowHost -}}
{{- .Values.global.opensearch.langflowHost -}}
{{- else -}}
{{- include "bomarag.opensearch.host" . -}}
{{- end -}}
{{- end }}

{{/*
Generate the Langflow-specific OpenSearch Port
*/}}
{{- define "bomarag.langflow.opensearch.port" -}}
{{- default .Values.global.opensearch.port .Values.global.opensearch.langflowPort }}
{{- end }}

{{/*
Generate the Langflow-specific OpenSearch URL
*/}}
{{- define "bomarag.langflow.opensearch.url" -}}
{{ .Values.global.opensearch.scheme }}://{{ include "bomarag.langflow.opensearch.host" . }}:{{ include "bomarag.langflow.opensearch.port" . }}
{{- end }}

{{/*
Generate the Docling URL
*/}}
{{- define "bomarag.docling.url" -}}
{{ .Values.global.docling.scheme }}://{{ .Values.global.docling.host }}:{{ .Values.global.docling.port }}
{{- end }}

{{/*
PostgreSQL component labels
*/}}
{{- define "bomarag.postgres.labels" -}}
{{ include "bomarag.labels" . }}
app.kubernetes.io/component: postgres
{{- end }}

{{/*
PostgreSQL selector labels
*/}}
{{- define "bomarag.postgres.selectorLabels" -}}
{{ include "bomarag.selectorLabels" . }}
app.kubernetes.io/component: postgres
{{- end }}

{{/*
Generate the PostgreSQL service URL
*/}}
{{- define "bomarag.postgres.url" -}}
postgresql://{{ .Values.postgres.username }}@{{ include "bomarag.fullname" . }}-postgres:{{ .Values.postgres.service.port }}/{{ .Values.postgres.database }}
{{- end }}

{{/*
Generate a strong random password for PostgreSQL
Uses derivePassword for deterministic generation based on release context
This ensures the same password is generated across all templates in a single Helm operation
Always generates a secure 32-character password stored only in Kubernetes secret
Note: Password is auto-generated on first install and persists in the secret
*/}}
{{- define "bomarag.postgres.password" -}}
{{- derivePassword 1 "maximum" .Release.Name "bomarag-postgres" .Chart.Name -}}
{{- end -}}

{{/*
Generate a strong random session secret for Backend
Uses derivePassword for deterministic generation based on release context
This ensures the same secret is generated across all templates in a single Helm operation
Always generates a secure session secret stored only in Kubernetes secret
Note: Secret is auto-generated on first install and persists in the secret
*/}}
{{- define "bomarag.backend.sessionSecret" -}}
{{- derivePassword 1 "maximum" .Release.Name "bomarag-backend-session" .Chart.Name -}}
{{- end -}}