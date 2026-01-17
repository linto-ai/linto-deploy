{{/*
Expand the name of the chart.
*/}}
{{- define "linto-stt.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "linto-stt.fullname" -}}
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
{{- define "linto-stt.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "linto-stt.labels" -}}
helm.sh/chart: {{ include "linto-stt.chart" . }}
{{ include "linto-stt.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "linto-stt.selectorLabels" -}}
app.kubernetes.io/name: {{ include "linto-stt.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image tag helper
*/}}
{{- define "linto-stt.imageTag" -}}
{{- .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Redis host
*/}}
{{- define "linto-stt.redisHost" -}}
{{- printf "%s-redis" .Release.Name }}
{{- end }}

{{/*
MongoDB host
*/}}
{{- define "linto-stt.mongodbHost" -}}
{{- printf "%s-mongodb" .Release.Name }}
{{- end }}

{{/*
Broker URL
*/}}
{{- define "linto-stt.brokerUrl" -}}
{{- printf "redis://%s:6379" (include "linto-stt.redisHost" .) }}
{{- end }}

{{/*
TLS secret name - uses shared secret if configured
*/}}
{{- define "linto-stt.tlsSecretName" -}}
{{- if .Values.global.tls.secretName }}
{{- .Values.global.tls.secretName }}
{{- else }}
{{- printf "%s-tls" .Release.Name }}
{{- end }}
{{- end }}

{{/*
URL scheme based on TLS settings
*/}}
{{- define "linto-stt.scheme" -}}
{{- if .Values.global.tls.enabled }}https{{- else }}http{{- end }}
{{- end }}

{{/*
API Gateway host - used by transcription service to register
*/}}
{{- define "linto-stt.gatewayHost" -}}
{{- printf "%s-api-gateway" .Release.Name }}
{{- end }}

{{/*
Image pull policy - Always for latest-* tags, otherwise use configured value
*/}}
{{- define "linto-stt.imagePullPolicy" -}}
{{- $tag := include "linto-stt.imageTag" . -}}
{{- if hasPrefix "latest" $tag -}}
Always
{{- else -}}
IfNotPresent
{{- end -}}
{{- end }}
