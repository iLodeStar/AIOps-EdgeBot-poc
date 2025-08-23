{{/*
Expand the name of the chart.
*/}}
{{- define "observability.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "observability.fullname" -}}
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
{{- define "observability.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "observability.labels" -}}
helm.sh/chart: {{ include "observability.chart" . }}
{{ include "observability.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.global.commonLabels }}
{{- toYaml . | nindent 0 }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "observability.selectorLabels" -}}
app.kubernetes.io/name: {{ include "observability.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Generate Loki URL for Grafana datasource
*/}}
{{- define "observability.lokiUrl" -}}
{{- if .Values.loki.enabled }}
{{- if .Values.loki.standalone }}
{{- printf "%s-loki" (include "observability.fullname" .) }}
{{- else }}
{{- printf "%s-loki" (include "observability.fullname" .) }}
{{- end }}
{{- else }}
{{- printf "loki" }}
{{- end }}
{{- end }}

{{/*
Generate Prometheus URL
*/}}
{{- define "observability.prometheusUrl" -}}
{{- if .Values.prometheus.enabled }}
{{- printf "%s-prometheus" (include "observability.fullname" .) }}
{{- else }}
{{- printf "prometheus" }}
{{- end }}
{{- end }}

{{/*
Generate mothership target for Prometheus scraping
*/}}
{{- define "observability.mothershipTarget" -}}
{{- printf "%s.%s.svc.cluster.local:8080" .Values.edgebot.mothershipServiceName .Values.edgebot.mothershipNamespace }}
{{- end }}