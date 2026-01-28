{{/*
Expand the name of the chart.
*/}}
{{- define "linto-studio.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "linto-studio.fullname" -}}
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
{{- define "linto-studio.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "linto-studio.labels" -}}
helm.sh/chart: {{ include "linto-studio.chart" . }}
{{ include "linto-studio.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "linto-studio.selectorLabels" -}}
app.kubernetes.io/name: {{ include "linto-studio.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component labels
*/}}
{{- define "linto-studio.componentLabels" -}}
{{ include "linto-studio.labels" . }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
MongoDB host
*/}}
{{- define "linto-studio.mongodbHost" -}}
{{- printf "%s-mongodb" .Release.Name }}
{{- end }}

{{/*
TLS secret name - uses shared secret if configured
*/}}
{{- define "linto-studio.tlsSecretName" -}}
{{- if .Values.global.tls.secretName }}
{{- .Values.global.tls.secretName }}
{{- else }}
{{- printf "%s-tls" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Image tag helper - returns global tag
*/}}
{{- define "linto-studio.imageTag" -}}
{{- .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Service-specific image tag helper
Usage: {{ include "linto-studio.serviceImageTag" (dict "service" .Values.studioApi "global" .Values.global "chart" .Chart) }}
*/}}
{{- define "linto-studio.serviceImageTag" -}}
{{- if .service.image.tag }}
{{- .service.image.tag }}
{{- else }}
{{- .global.imageTag | default .chart.AppVersion }}
{{- end }}
{{- end }}

{{/*
URL scheme based on TLS
*/}}
{{- define "linto-studio.scheme" -}}
{{- if .Values.global.tls.enabled }}https{{- else }}http{{- end }}
{{- end }}

{{/*
Image pull policy - Always for latest-* tags, otherwise use configured value
*/}}
{{- define "linto-studio.imagePullPolicy" -}}
{{- $tag := include "linto-studio.imageTag" . -}}
{{- if hasPrefix "latest" $tag -}}
Always
{{- else -}}
{{ .pullPolicy | default "IfNotPresent" }}
{{- end -}}
{{- end }}
