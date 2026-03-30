{{/*
Expand the name of the chart.
*/}}
{{- define "openrag.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
If tenant name is provided, prefix with tenant name.
*/}}
{{- define "openrag.fullname" -}}
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
{{- define "openrag.namespace" -}}
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
{{- define "openrag.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "openrag.labels" -}}
helm.sh/chart: {{ include "openrag.chart" . }}
{{ include "openrag.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.global.tenant.name }}
openrag.io/tenant: {{ .Values.global.tenant.name }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "openrag.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openrag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "openrag.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "openrag.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Langflow component labels
*/}}
{{- define "openrag.langflow.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: langflow
{{- end }}

{{/*
Langflow selector labels
*/}}
{{- define "openrag.langflow.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: langflow
{{- end }}

{{/*
Backend component labels
*/}}
{{- define "openrag.backend.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Backend selector labels
*/}}
{{- define "openrag.backend.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Frontend component labels
*/}}
{{- define "openrag.frontend.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Frontend selector labels
*/}}
{{- define "openrag.frontend.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Dashboards component labels
*/}}
{{- define "openrag.dashboards.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: dashboards
{{- end }}

{{/*
Dashboards selector labels
*/}}
{{- define "openrag.dashboards.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: dashboards
{{- end }}

{{/*
Generate the Langflow service URL
*/}}
{{- define "openrag.langflow.url" -}}
http://{{ include "openrag.fullname" . }}-langflow:{{ .Values.langflow.service.port }}
{{- end }}

{{/*
Generate the Backend service URL
*/}}
{{- define "openrag.backend.url" -}}
http://{{ include "openrag.fullname" . }}-backend:{{ .Values.backend.service.port }}
{{- end }}

{{/*
Generate the OpenSearch URL
*/}}
{{- define "openrag.opensearch.url" -}}
{{ .Values.global.opensearch.scheme }}://{{ .Values.global.opensearch.host }}:{{ .Values.global.opensearch.port }}
{{- end }}

{{/*
Generate the Docling URL
*/}}
{{- define "openrag.docling.url" -}}
{{ .Values.global.docling.scheme }}://{{ .Values.global.docling.host }}:{{ .Values.global.docling.port }}
{{- end }}

{{/*
PostgreSQL component labels
*/}}
{{- define "openrag.postgres.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: postgres
{{- end }}

{{/*
PostgreSQL selector labels
*/}}
{{- define "openrag.postgres.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: postgres
{{- end }}

{{/*
Generate the PostgreSQL service URL
*/}}
{{- define "openrag.postgres.url" -}}
postgresql://{{ .Values.postgres.username }}@{{ include "openrag.fullname" . }}-postgres:{{ .Values.postgres.service.port }}/{{ .Values.postgres.database }}
{{- end }}

{{/*
Generate a strong random password for PostgreSQL
Uses derivePassword for deterministic generation based on release context
This ensures the same password is generated across all templates in a single Helm operation
Always generates a secure 32-character password stored only in Kubernetes secret
Note: Password is auto-generated on first install and persists in the secret
*/}}
{{- define "openrag.postgres.password" -}}
{{- derivePassword 1 "maximum" .Release.Name "openrag-postgres" .Chart.Name -}}
{{- end -}}

{{/*
Generate a strong random session secret for Backend
Uses derivePassword for deterministic generation based on release context
This ensures the same secret is generated across all templates in a single Helm operation
Always generates a secure session secret stored only in Kubernetes secret
Note: Secret is auto-generated on first install and persists in the secret
*/}}
{{- define "openrag.backend.sessionSecret" -}}
{{- derivePassword 1 "maximum" .Release.Name "openrag-backend-session" .Chart.Name -}}
{{- end -}}