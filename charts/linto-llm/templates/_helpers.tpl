{{/*
Expand the name of the chart.
*/}}
{{- define "linto-llm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "linto-llm.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "linto-llm.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "linto-llm.labels" -}}
helm.sh/chart: {{ include "linto-llm.chart" . }}
{{ include "linto-llm.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "linto-llm.selectorLabels" -}}
app.kubernetes.io/name: {{ include "linto-llm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image tag helper
*/}}
{{- define "linto-llm.imageTag" -}}
{{- .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Redis host
*/}}
{{- define "linto-llm.redisHost" -}}
{{- printf "%s-redis" .Release.Name }}
{{- end }}

{{/*
PostgreSQL host
*/}}
{{- define "linto-llm.postgresHost" -}}
{{- printf "%s-postgres" .Release.Name }}
{{- end }}

{{/*
Broker URL
*/}}
{{- define "linto-llm.brokerUrl" -}}
{{- printf "redis://%s:6379" (include "linto-llm.redisHost" .) }}
{{- end }}

{{/*
vLLM service URL
*/}}
{{- define "linto-llm.vllmUrl" -}}
{{- printf "http://%s-vllm:8000/v1" .Release.Name }}
{{- end }}

{{/*
Database URL (without password - added via env var)
*/}}
{{- define "linto-llm.databaseUrl" -}}
{{- printf "postgresql://llm_user@%s:5432/llm_DB" (include "linto-llm.postgresHost" .) }}
{{- end }}

{{/*
Celery broker URL (with password placeholder)
*/}}
{{- define "linto-llm.celeryBrokerUrl" -}}
{{- printf "redis://:%s@%s:6379/0" "$(REDIS_PASSWORD)" (include "linto-llm.redisHost" .) }}
{{- end }}

{{/*
TLS secret name - uses shared secret if configured
*/}}
{{- define "linto-llm.tlsSecretName" -}}
{{- if .Values.global.tls.secretName }}
{{- .Values.global.tls.secretName }}
{{- else }}
{{- printf "%s-tls" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Image pull policy - Always for latest-* tags, otherwise use configured value
*/}}
{{- define "linto-llm.imagePullPolicy" -}}
{{- $tag := include "linto-llm.imageTag" . -}}
{{- if hasPrefix "latest" $tag -}}
Always
{{- else -}}
IfNotPresent
{{- end -}}
{{- end }}
