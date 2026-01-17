{{/*
Expand the name of the chart.
*/}}
{{- define "linto-live.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "linto-live.fullname" -}}
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
{{- define "linto-live.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "linto-live.labels" -}}
helm.sh/chart: {{ include "linto-live.chart" . }}
{{ include "linto-live.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "linto-live.selectorLabels" -}}
app.kubernetes.io/name: {{ include "linto-live.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image tag helper
*/}}
{{- define "linto-live.imageTag" -}}
{{- .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
PostgreSQL host
*/}}
{{- define "linto-live.postgresHost" -}}
{{- printf "%s-postgres" .Release.Name }}
{{- end }}

{{/*
Broker host
*/}}
{{- define "linto-live.brokerHost" -}}
{{- printf "%s-broker" .Release.Name }}
{{- end }}

{{/*
Transcriber host
*/}}
{{- define "linto-live.transcriberHost" -}}
{{- printf "%s-transcriber" .Release.Name }}
{{- end }}

{{/*
TLS secret name - uses shared secret if configured
*/}}
{{- define "linto-live.tlsSecretName" -}}
{{- if .Values.global.tls.secretName }}
{{- .Values.global.tls.secretName }}
{{- else }}
{{- printf "%s-tls" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Image pull policy - Always for latest-* tags, otherwise use configured value
*/}}
{{- define "linto-live.imagePullPolicy" -}}
{{- $tag := include "linto-live.imageTag" . -}}
{{- if hasPrefix "latest" $tag -}}
Always
{{- else -}}
IfNotPresent
{{- end -}}
{{- end }}
