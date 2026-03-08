{{/*
Expand the name of the chart.
*/}}
{{- define "linto-vllm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "linto-vllm.fullname" -}}
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
{{- define "linto-vllm.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "linto-vllm.labels" -}}
helm.sh/chart: {{ include "linto-vllm.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image tag - defaults to global.imageTag
*/}}
{{- define "linto-vllm.imageTag" -}}
{{- .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Image pull policy - Always for latest/nightly tags
*/}}
{{- define "linto-vllm.imagePullPolicy" -}}
{{- if .Values.global.imagePullPolicy }}
{{- .Values.global.imagePullPolicy }}
{{- else }}
{{- $tag := include "linto-vllm.imageTag" . }}
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
Usage: {{ include "linto-vllm.extraArgsStr" (dict "args" $instance.extraArgs) }}
*/}}
{{- define "linto-vllm.extraArgsStr" -}}
{{- range .args }} '{{ . }}'{{ end -}}
{{- end }}

{{/*
Generate service URL for an instance.
Usage: {{ include "linto-vllm.serviceUrl" (dict "root" . "name" "voxtral") }}
*/}}
{{- define "linto-vllm.serviceUrl" -}}
{{- $instance := index .root.Values.instances .name }}
{{- printf "http://%s-%s:%d" (include "linto-vllm.fullname" .root) .name ($instance.service.port | int) }}
{{- end }}
