{{/*
Diarization GPU workers, one Deployment per GPU index with replicas > 0.
Args: root (chart context), cfg (values block), component (label and name part),
modelsCache (mount the shared models cache; images with baked models do not need it).
*/}}
{{- define "linto-stt.diarizationWorkers" -}}
{{- $root := .root -}}
{{- $cfg := .cfg -}}
{{- $component := .component -}}
{{- $modelsCache := .modelsCache -}}
{{- range $gpuIndex, $replicas := $cfg.replicasPerGpu }}
{{- if gt (int $replicas) 0 }}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "linto-stt.fullname" $root }}-{{ $component }}-gpu-{{ $gpuIndex }}
  labels:
    {{- include "linto-stt.labels" $root | nindent 4 }}
    app.kubernetes.io/component: {{ $component }}
    gpu-index: "{{ $gpuIndex }}"
spec:
  revisionHistoryLimit: 5
  replicas: {{ $replicas }}
  selector:
    matchLabels:
      {{- include "linto-stt.selectorLabels" $root | nindent 6 }}
      app.kubernetes.io/component: {{ $component }}
      gpu-index: "{{ $gpuIndex }}"
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $root.Template.BasePath "/configmap.yaml") $root | sha256sum }}
      labels:
        {{- include "linto-stt.selectorLabels" $root | nindent 8 }}
        app.kubernetes.io/component: {{ $component }}
        gpu-index: "{{ $gpuIndex }}"
    spec:
      {{- with $root.Values.global.gpuScheduling.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with $root.Values.global.gpuScheduling.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/component: {{ $component }}
                    gpu-index: "{{ $gpuIndex }}"
                topologyKey: kubernetes.io/hostname
      {{- if $modelsCache }}
      initContainers:
        - name: fix-permissions
          image: busybox:latest
          command: ["sh", "-c", "chown -R 33:33 /var/www/.cache && chmod -R 775 /var/www/.cache"]
          volumeMounts:
            - name: models-cache
              mountPath: /var/www/.cache
          securityContext:
            runAsUser: 0
      {{- end }}
      containers:
        - name: diarization
          image: "{{ $cfg.image.repository }}:{{ $cfg.image.tag | default (include "linto-stt.imageTag" $root) }}"
          imagePullPolicy: {{ include "linto-stt.imagePullPolicy" $root }}
          envFrom:
            - configMapRef:
                name: {{ include "linto-stt.fullname" $root }}-{{ $component }}-config
          env:
            - name: BROKER_PASS
              valueFrom:
                secretKeyRef:
                  name: {{ include "linto-stt.fullname" $root }}-secrets
                  key: redis-password
            - name: NVIDIA_VISIBLE_DEVICES
              value: "{{ $gpuIndex }}"
          volumeMounts:
            - name: audio-shared
              mountPath: /opt/audio
            {{- if $modelsCache }}
            - name: models-cache
              mountPath: /var/www/.cache
            {{- end }}
          livenessProbe:
            exec:
              command:
                - /usr/src/app/healthcheck.sh
            initialDelaySeconds: 120
            periodSeconds: 60
            timeoutSeconds: 30
            failureThreshold: 3
          resources:
            limits:
              nvidia.com/gpu: 1
            requests:
              {{- if $cfg.resources }}
              {{- if $cfg.resources.requests }}
              {{- toYaml $cfg.resources.requests | nindent 14 }}
              {{- end }}
              {{- end }}
      volumes:
        - name: audio-shared
          {{- if $root.Values.global.storage.files.hostPath }}
          hostPath:
            path: {{ $root.Values.global.storage.files.hostPath }}/stt-audio
            type: DirectoryOrCreate
          {{- else }}
          emptyDir: {}
          {{- end }}
        {{- if $modelsCache }}
        - name: models-cache
          {{- if $root.Values.global.storage.files.hostPath }}
          hostPath:
            path: {{ $root.Values.global.storage.files.hostPath }}/models-cache
            type: DirectoryOrCreate
          {{- else }}
          emptyDir: {}
          {{- end }}
        {{- end }}
{{- end }}
{{- end }}
{{- end }}
