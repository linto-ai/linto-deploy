{{/*
Expand the name of the chart.
*/}}
{{- define "linto-vllm-hc.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "linto-vllm-hc.fullname" -}}
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
{{- define "linto-vllm-hc.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "linto-vllm-hc.labels" -}}
helm.sh/chart: {{ include "linto-vllm-hc.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image tag - defaults to global.imageTag
*/}}
{{- define "linto-vllm-hc.imageTag" -}}
{{- .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Image pull policy - Always for latest/nightly tags
*/}}
{{- define "linto-vllm-hc.imagePullPolicy" -}}
{{- if .Values.global.imagePullPolicy }}
{{- .Values.global.imagePullPolicy }}
{{- else }}
{{- $tag := include "linto-vllm-hc.imageTag" . }}
{{- if or (hasPrefix "latest" $tag) (eq $tag "nightly") }}
Always
{{- else }}
IfNotPresent
{{- end }}
{{- end }}
{{- end }}

{{/*
Join extra args into a shell-safe string for command mode.
Args containing special chars ({, spaces) are single-quoted for shell safety.
Usage: {{ include "linto-vllm-hc.extraArgsStr" (dict "args" $instance.extraArgs) }}
*/}}
{{- define "linto-vllm-hc.extraArgsStr" -}}
{{- range .args }} '{{ . }}'{{ end -}}
{{- end }}

{{/*
Generate service URL for an instance.
Usage: {{ include "linto-vllm-hc.serviceUrl" (dict "root" . "name" "voxtral") }}
*/}}
{{- define "linto-vllm-hc.serviceUrl" -}}
{{- $instance := index .root.Values.instances .name }}
{{- printf "http://%s-%s:%d" (include "linto-vllm-hc.fullname" .root) .name ($instance.service.port | int) }}
{{- end }}
